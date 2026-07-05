"""Gig platform service — create, list, update, delete."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.gig_platform import GigPlatform
from app.repositories.gig_platform import GigPlatformRepository
from app.schemas.gig_platform import GigPlatformCreateRequest, GigPlatformUpdateRequest


class GigPlatformService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = GigPlatformRepository(session)

    async def create(self, user_id: UUID, payload: GigPlatformCreateRequest) -> GigPlatform:
        item = GigPlatform(
            user_id=user_id,
            platform_name=payload.platform_name,
            partner_role=payload.partner_role,
            started_at=payload.started_at,
            ended_at=payload.ended_at,
            is_active=payload.is_active,
            partner_id=payload.partner_id,
            rating=payload.rating,
        )
        await self._repo.create(item)
        await self._session.commit()
        await self._session.refresh(item)
        return item

    async def list_for_user(self, user_id: UUID, *, offset: int = 0, limit: int = 50):
        return await self._repo.list_for_user(user_id, offset=offset, limit=limit)

    async def get_owned(self, user_id: UUID, item_id: UUID) -> GigPlatform:
        item = await self._repo.get_owned(item_id, user_id)
        if item is None:
            raise NotFoundError("Gig platform not found")
        return item

    async def update(
        self, user_id: UUID, item_id: UUID, payload: GigPlatformUpdateRequest,
    ) -> GigPlatform:
        item = await self.get_owned(user_id, item_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(item, field, value)
        await self._session.commit()
        await self._session.refresh(item)
        return item

    async def delete(self, user_id: UUID, item_id: UUID) -> None:
        item = await self.get_owned(user_id, item_id)
        await self._repo.soft_delete(item)
        await self._session.commit()
