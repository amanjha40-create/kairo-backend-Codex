"""Repository for internship records."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internship import Internship


class InternshipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, item: Internship) -> Internship:
        self._session.add(item)
        await self._session.flush()
        return item

    async def get_owned(self, item_id: UUID, user_id: UUID) -> Internship | None:
        stmt = select(Internship).where(
            Internship.id == item_id,
            Internship.user_id == user_id,
            Internship.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(
        self, user_id: UUID, *, offset: int = 0, limit: int = 50,
    ) -> tuple[list[Internship], int]:
        base = (
            Internship.user_id == user_id,
            Internship.deleted_at.is_(None),
        )
        total = int((await self._session.execute(
            select(func.count()).select_from(Internship).where(*base)
        )).scalar_one())
        rows = list((await self._session.execute(
            select(Internship).where(*base).order_by(Internship.start_date.desc()).offset(offset).limit(limit)
        )).scalars().all())
        return rows, total

    async def soft_delete(self, item: Internship) -> None:
        item.deleted_at = datetime.now(tz=UTC)
        await self._session.flush()
