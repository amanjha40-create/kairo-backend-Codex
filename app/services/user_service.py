"""User profile use cases — wraps repository access for HTTP boundaries."""

from __future__ import annotations

import mimetypes
from urllib.parse import urlparse
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.phone_utils import normalize_phone
from app.config import Settings
from app.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.infrastructure.s3.paths import build_user_avatar_key
from app.infrastructure.s3.presign import generate_presigned_get_url, generate_presigned_put_url
from app.infrastructure.s3.service import S3UploadService
from app.models import ProfileLanguage, ProfileLink
from app.schemas.profile import (
    ProfileLanguageCreate,
    ProfileLanguageResponse,
    ProfileLanguageUpdate,
    ProfileLinkCreate,
    ProfileLinkResponse,
    ProfileLinkUpdate,
)
from app.repositories import UserRepository
from app.schemas.user import AvatarUploadIntentResponse, UserPublic, UserUpdate

_AVATAR_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days
_AVATAR_MAX_BYTES = 5 * 1024 * 1024
_AVATAR_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


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
        return await self._to_public(user)

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
        return await self._to_public(user)

    async def _to_public(self, user) -> UserPublic:  # noqa: ANN001
        languages = list((await self._session.execute(
            select(ProfileLanguage).where(ProfileLanguage.user_id == user.id).order_by(ProfileLanguage.language.asc())
        )).scalars().all())
        links = list((await self._session.execute(
            select(ProfileLink).where(ProfileLink.user_id == user.id).order_by(ProfileLink.created_at.asc())
        )).scalars().all())
        pub = UserPublic.model_validate(user)
        pub.avatar_url = await self._avatar_url(user.avatar_key)
        pub.languages = [ProfileLanguageResponse.model_validate(item) for item in languages]
        pub.professional_links = [ProfileLinkResponse.model_validate(item) for item in links]
        pub.profile_completion_percentage = self._profile_completion(user, languages, links)
        return pub

    @staticmethod
    def _profile_completion(user, languages: list[ProfileLanguage], links: list[ProfileLink]) -> int:  # noqa: ANN001
        requirements = [
            bool((user.full_name or "").strip()),
            bool(user.avatar_key),
            bool((user.headline or "").strip()),
            bool((user.bio or "").strip()),
            bool(user.email_verified_at),
            bool(user.phone_verified_at),
            bool((user.location_city or user.location_country or user.location or "").strip()),
            bool(languages),
            bool(links),
        ]
        return int(sum(requirements) * 100 / len(requirements))

    async def list_languages(self, user_id: UUID) -> list[ProfileLanguageResponse]:
        rows = (await self._session.execute(
            select(ProfileLanguage).where(ProfileLanguage.user_id == user_id).order_by(ProfileLanguage.language.asc())
        )).scalars().all()
        return [ProfileLanguageResponse.model_validate(row) for row in rows]

    async def create_language(self, user_id: UUID, payload: ProfileLanguageCreate) -> ProfileLanguageResponse:
        language = payload.language.casefold()
        existing = await self._session.scalar(select(ProfileLanguage).where(ProfileLanguage.user_id == user_id, ProfileLanguage.language.ilike(language)))
        if existing:
            raise ConflictError("This language is already on your profile")
        row = ProfileLanguage(user_id=user_id, language=payload.language, proficiency=payload.proficiency)
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return ProfileLanguageResponse.model_validate(row)

    async def update_language(self, user_id: UUID, language_id: UUID, payload: ProfileLanguageUpdate) -> ProfileLanguageResponse:
        row = await self._session.scalar(select(ProfileLanguage).where(ProfileLanguage.id == language_id, ProfileLanguage.user_id == user_id))
        if row is None:
            raise NotFoundError("Language not found")
        changes = payload.model_dump(exclude_unset=True)
        if "language" in changes:
            duplicate = await self._session.scalar(select(ProfileLanguage).where(ProfileLanguage.user_id == user_id, ProfileLanguage.id != language_id, ProfileLanguage.language.ilike(changes["language"])))
            if duplicate:
                raise ConflictError("This language is already on your profile")
        for field, value in changes.items():
            setattr(row, field, value)
        await self._session.commit()
        await self._session.refresh(row)
        return ProfileLanguageResponse.model_validate(row)

    async def delete_language(self, user_id: UUID, language_id: UUID) -> None:
        row = await self._session.scalar(select(ProfileLanguage).where(ProfileLanguage.id == language_id, ProfileLanguage.user_id == user_id))
        if row is None:
            raise NotFoundError("Language not found")
        await self._session.delete(row)
        await self._session.commit()

    async def list_links(self, user_id: UUID) -> list[ProfileLinkResponse]:
        rows = (await self._session.execute(
            select(ProfileLink).where(ProfileLink.user_id == user_id).order_by(ProfileLink.created_at.asc())
        )).scalars().all()
        return [ProfileLinkResponse.model_validate(row) for row in rows]

    @staticmethod
    def _normalize_url(value: str) -> str:
        candidate = value.strip()
        if "://" not in candidate:
            if ":" in candidate.split("/", 1)[0]:
                raise ValidationAppError("Enter a valid professional link")
            candidate = f"https://{candidate}"
        parsed = urlparse(candidate)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
        ):
            raise ValidationAppError("Enter a valid professional link")
        return candidate

    async def create_link(self, user_id: UUID, payload: ProfileLinkCreate) -> ProfileLinkResponse:
        url = self._normalize_url(payload.url)
        existing = await self._session.scalar(select(ProfileLink).where(ProfileLink.user_id == user_id, ProfileLink.url == url))
        if existing:
            raise ConflictError("This professional link is already on your profile")
        row = ProfileLink(user_id=user_id, link_type=payload.link_type, label=payload.label, url=url)
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return ProfileLinkResponse.model_validate(row)

    async def update_link(self, user_id: UUID, link_id: UUID, payload: ProfileLinkUpdate) -> ProfileLinkResponse:
        row = await self._session.scalar(select(ProfileLink).where(ProfileLink.id == link_id, ProfileLink.user_id == user_id))
        if row is None:
            raise NotFoundError("Professional link not found")
        changes = payload.model_dump(exclude_unset=True)
        if "url" in changes and changes["url"]:
            changes["url"] = self._normalize_url(changes["url"])
            duplicate = await self._session.scalar(select(ProfileLink).where(ProfileLink.user_id == user_id, ProfileLink.id != link_id, ProfileLink.url == changes["url"]))
            if duplicate:
                raise ConflictError("This professional link is already on your profile")
        for field, value in changes.items():
            setattr(row, field, value)
        await self._session.commit()
        await self._session.refresh(row)
        return ProfileLinkResponse.model_validate(row)

    async def delete_link(self, user_id: UUID, link_id: UUID) -> None:
        row = await self._session.scalar(select(ProfileLink).where(ProfileLink.id == link_id, ProfileLink.user_id == user_id))
        if row is None:
            raise NotFoundError("Professional link not found")
        await self._session.delete(row)
        await self._session.commit()

    async def remove_avatar(self, user_id: UUID) -> None:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")
        old_key = user.avatar_key
        user.avatar_key = None
        await self._session.commit()
        if old_key:
            await S3UploadService(self._settings).delete_object_best_effort(object_key=old_key)

    async def complete_avatar_upload(self, user_id: UUID) -> UserPublic:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")
        if not user.avatar_key:
            raise ValidationAppError("Profile photo upload has not been started")
        try:
            metadata = await S3UploadService(self._settings).head_object(object_key=user.avatar_key)
        except Exception as exc:
            user.avatar_key = None
            await self._session.commit()
            raise ValidationAppError("Profile photo upload could not be verified") from exc
        content_type = str(metadata.get("ContentType") or "").split(";", 1)[0].lower()
        size = int(metadata.get("ContentLength") or 0)
        if content_type not in _AVATAR_CONTENT_TYPES or size <= 0 or size > _AVATAR_MAX_BYTES:
            user.avatar_key = None
            await self._session.commit()
            raise ValidationAppError("Profile photo must be a JPG, PNG, or WebP image up to 5 MB")
        await self._session.refresh(user)
        return await self._to_public(user)

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
