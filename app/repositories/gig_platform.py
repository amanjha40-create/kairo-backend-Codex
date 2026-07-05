"""Repository for gig platform records."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.gig_platform import GigPlatform


class GigPlatformRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, item: GigPlatform) -> GigPlatform:
        self._session.add(item)
        await self._session.flush()
        return item

    async def get_owned(self, item_id: UUID, user_id: UUID) -> GigPlatform | None:
        stmt = select(GigPlatform).where(
            GigPlatform.id == item_id,
            GigPlatform.user_id == user_id,
            GigPlatform.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(
        self, user_id: UUID, *, offset: int = 0, limit: int = 50,
    ) -> tuple[list[GigPlatform], int]:
        base = (
            GigPlatform.user_id == user_id,
            GigPlatform.deleted_at.is_(None),
        )
        total = int((await self._session.execute(
            select(func.count()).select_from(GigPlatform).where(*base)
        )).scalar_one())
        rows = list((await self._session.execute(
            select(GigPlatform).where(*base).order_by(GigPlatform.started_at.desc()).offset(offset).limit(limit)
        )).scalars().all())
        return rows, total

    async def soft_delete(self, item: GigPlatform) -> None:
        item.deleted_at = datetime.now(tz=UTC)
        await self._session.flush()
