"""Repository for certification records."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.certification import Certification


class CertificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, item: Certification) -> Certification:
        self._session.add(item)
        await self._session.flush()
        return item

    async def get_owned(self, item_id: UUID, user_id: UUID) -> Certification | None:
        stmt = select(Certification).where(
            Certification.id == item_id,
            Certification.user_id == user_id,
            Certification.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(
        self, user_id: UUID, *, offset: int = 0, limit: int = 50,
    ) -> tuple[list[Certification], int]:
        base = (
            Certification.user_id == user_id,
            Certification.deleted_at.is_(None),
        )
        total = int((await self._session.execute(
            select(func.count()).select_from(Certification).where(*base)
        )).scalar_one())
        rows = list((await self._session.execute(
            select(Certification).where(*base)
            .order_by(Certification.issued_date.desc())
            .offset(offset)
            .limit(limit)
        )).scalars().all())
        return rows, total

    async def soft_delete(self, item: Certification) -> None:
        item.deleted_at = datetime.now(tz=UTC)
        await self._session.flush()
