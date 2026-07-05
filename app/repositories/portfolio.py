"""Repository for portfolio items."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio import PortfolioItem


class PortfolioRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, item: PortfolioItem) -> PortfolioItem:
        self._session.add(item)
        await self._session.flush()
        return item

    async def get_owned(self, item_id: UUID, user_id: UUID) -> PortfolioItem | None:
        stmt = select(PortfolioItem).where(
            PortfolioItem.id == item_id,
            PortfolioItem.user_id == user_id,
            PortfolioItem.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[PortfolioItem], int]:
        base_filter = (
            PortfolioItem.user_id == user_id,
            PortfolioItem.deleted_at.is_(None),
        )
        count_stmt = select(func.count()).select_from(PortfolioItem).where(*base_filter)
        total = int((await self._session.execute(count_stmt)).scalar_one())

        list_stmt = (
            select(PortfolioItem)
            .where(*base_filter)
            .order_by(PortfolioItem.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = list((await self._session.execute(list_stmt)).scalars().all())
        return rows, total

    async def soft_delete(self, item: PortfolioItem) -> None:
        item.deleted_at = datetime.now(tz=UTC)
        await self._session.flush()
