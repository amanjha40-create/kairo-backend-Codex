"""User profile use cases — wraps repository access for HTTP boundaries."""

from __future__ import annotations

import mimetypes
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.phone_utils import normalize_phone
from app.config import Settings
from app.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.infrastructure.s3.paths import build_user_avatar_key
from app.infrastructure.s3.presign import generate_presigned_get_url, generate_presigned_put_url
from app.repositories import UserRepository
from app.schemas.user import AvatarUploadIntentResponse, UserPublic, UserUpdate

_AVATAR_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days


class UserService:
    """Profile reads and updates (preferences, contact info, avatar, etc.)."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._users = UserRepository(session)

    async def _avatar_url(self, avatar_key: str | None) -> str | None:
        if not avatar_key or not self._settings.s3_documents_bucket:
            return None
        return await generate_presigned_get_url(
            bucket=self._settings.s3_documents_bucket,
            object_key=avatar_key,
            ttl_seconds=_AVATAR_TTL_SECONDS,
            settings=self._settings,
        )

    async def get_public_profile(self, user_id: UUID) -> UserPublic:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")
        pub = UserPublic.model_validate(user)
        pub.avatar_url = await self._avatar_url(user.avatar_key)
        return pub

    async def update_profile(self, user_id: UUID, data: UserUpdate) -> UserPublic:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")

        changes = data.model_dump(exclude_unset=True)
        if "phone" in changes and changes["phone"]:
            normalized_phone = normalize_phone(changes["phone"], self._settings)
            existing = await self._users.get_by_phone(normalized_phone)
            if existing is not None and existing.id != user.id:
                raise ConflictError("Phone number is already in use")
            if normalized_phone != user.phone:
                user.phone_verified_at = None
            changes["phone"] = normalized_phone

        for field, value in changes.items():
            setattr(user, field, value)

        if self._is_minimum_onboarding_complete(user) and user.employment_onboarding_completed_at is None:
            user.employment_onboarding_completed_at = datetime.now(timezone.utc)

        await self._session.commit()
        await self._session.refresh(user)
        pub = UserPublic.model_validate(user)
        pub.avatar_url = await self._avatar_url(user.avatar_key)
        return pub

    async def complete_onboarding(self, user_id: UUID) -> None:
        """Mark onboarding done — idempotent, first call wins."""
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")
        if user.employment_onboarding_completed_at is None:
            user.employment_onboarding_completed_at = datetime.now(timezone.utc)
            await self._session.commit()

    async def create_avatar_upload_intent(
        self,
        user_id: UUID,
        content_type: str,
    ) -> AvatarUploadIntentResponse:
        bucket = self._settings.s3_documents_bucket
        if not bucket:
            raise ValidationAppError("Avatar uploads are not configured (missing S3 bucket)")

        allowed = {"image/jpeg", "image/png", "image/webp", "image/gif"}
        if content_type not in allowed:
            raise ValidationAppError(f"Unsupported avatar type. Allowed: {', '.join(sorted(allowed))}")

        ext = mimetypes.guess_extension(content_type) or ".jpg"
        ext = ext.lstrip(".")
        if ext == "jpe":
            ext = "jpg"

        avatar_key = build_user_avatar_key(
            owner_user_id=user_id,
            extension=ext,
            prefix=self._settings.s3_document_key_prefix,
        )

        upload_url = await generate_presigned_put_url(
            bucket=bucket,
            object_key=avatar_key,
            content_type=content_type,
            ttl_seconds=300,
            settings=self._settings,
        )

        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")
        user.avatar_key = avatar_key
        await self._session.commit()

        avatar_url = await generate_presigned_get_url(
            bucket=bucket,
            object_key=avatar_key,
            ttl_seconds=_AVATAR_TTL_SECONDS,
            settings=self._settings,
        )

        return AvatarUploadIntentResponse(
            upload_url=upload_url,
            avatar_url=avatar_url,
            expires_in_seconds=300,
        )

    def _is_minimum_onboarding_complete(self, user) -> bool:  # noqa: ANN001
        return all(
            [
                bool(user.email_verified_at),
                bool(user.phone_verified_at),
                bool((user.full_name or "").strip()),
                bool((user.phone or "").strip()),
                bool((user.headline or "").strip()),
                bool((user.current_role or "").strip()),
                bool((user.industry or "").strip()),
                user.years_of_experience is not None,
            ]
        )
