"""Use cases for issuing and managing Trust Passport share links."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.exceptions import ConflictError, NotFoundError
from app.models.passport_share_link import PassportShareLink
from app.repositories.passport_share import PassportShareRepository
from app.schemas.passport_share import (
    PassportShareCreateRequest,
    PassportShareCreateResponse,
    PassportSharePermissions,
    PassportShareResponse,
    PassportShareUpdateRequest,
)


class PassportShareService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._repo = PassportShareRepository(session)

    async def create(self, owner_user_id: UUID, payload: PassportShareCreateRequest) -> PassportShareCreateResponse:
        raw_token = self._generate_raw_token()
        link = PassportShareLink(
            owner_user_id=owner_user_id,
            label=payload.label,
            token_hash=self._hash_token(raw_token),
            permissions=payload.permissions.model_dump(),
            track_views=payload.track_views,
            expires_at=payload.expires_at,
        )
        await self._repo.create(link)
        await self._session.commit()
        await self._session.refresh(link)
        response = self._to_response(link)
        return PassportShareCreateResponse(
            **response.model_dump(),
            share_url=self._build_share_url(raw_token),
        )

    async def list_for_user(
        self,
        owner_user_id: UUID,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[PassportShareResponse], int]:
        items, total = await self._repo.list_for_owner(owner_user_id, offset=offset, limit=limit)
        return [self._to_response(item) for item in items], total

    async def get_owned(self, owner_user_id: UUID, share_id: UUID) -> PassportShareResponse:
        link = await self._repo.get_owned(share_id, owner_user_id)
        if link is None:
            raise NotFoundError("Passport share link not found")
        return self._to_response(link)

    async def update(
        self,
        owner_user_id: UUID,
        share_id: UUID,
        payload: PassportShareUpdateRequest,
    ) -> PassportShareResponse:
        link = await self._repo.get_owned(share_id, owner_user_id)
        if link is None:
            raise NotFoundError("Passport share link not found")
        self._assert_mutable(link)

        updates = payload.model_dump(exclude_unset=True)
        if "label" in updates:
            link.label = updates["label"]
        if "expires_at" in updates:
            link.expires_at = updates["expires_at"]
        if "track_views" in updates:
            link.track_views = updates["track_views"]
        if "permissions" in updates and payload.permissions is not None:
            link.permissions = payload.permissions.model_dump()

        await self._session.commit()
        await self._session.refresh(link)
        return self._to_response(link)

    async def revoke(self, owner_user_id: UUID, share_id: UUID) -> PassportShareResponse:
        link = await self._repo.get_owned(share_id, owner_user_id)
        if link is None:
            raise NotFoundError("Passport share link not found")

        if link.revoked_at is None:
            link.revoked_at = datetime.now(tz=UTC)
            await self._session.commit()
            await self._session.refresh(link)

        return self._to_response(link)

    def _assert_mutable(self, link: PassportShareLink) -> None:
        if link.revoked_at is not None:
            raise ConflictError("Revoked share links cannot be updated. Create a new link instead.")
        if self._is_expired(link):
            raise ConflictError("Expired share links cannot be updated. Create a new link instead.")

    def _to_response(self, link: PassportShareLink) -> PassportShareResponse:
        return PassportShareResponse(
            id=link.id,
            label=link.label,
            permissions=PassportSharePermissions.model_validate(link.permissions or {}),
            track_views=link.track_views,
            expires_at=link.expires_at,
            revoked_at=link.revoked_at,
            last_viewed_at=link.last_viewed_at,
            created_at=link.created_at,
            updated_at=link.updated_at,
            state=self._state(link),
        )

    def _build_share_url(self, raw_token: str) -> str:
        base = self._settings.app_public_base_url.rstrip("/")
        return f"{base}/p/{raw_token}"

    def _state(self, link: PassportShareLink) -> str:
        if link.revoked_at is not None:
            return "revoked"
        if self._is_expired(link):
            return "expired"
        return "active"

    def _is_expired(self, link: PassportShareLink) -> bool:
        return link.expires_at is not None and link.expires_at <= datetime.now(tz=UTC)

    def _generate_raw_token(self) -> str:
        return secrets.token_urlsafe(32)

    def _hash_token(self, raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
