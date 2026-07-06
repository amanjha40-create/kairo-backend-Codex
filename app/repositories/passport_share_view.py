"""Repository for public Trust Passport share view events."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.passport_share_view import PassportShareView


class PassportShareViewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, view: PassportShareView) -> PassportShareView:
        self._session.add(view)
        await self._session.flush()
        return view

    async def has_recent_view(
        self,
        *,
        share_id: UUID,
        viewer_ip_hash: str,
        user_agent: str | None,
        cutoff: datetime,
    ) -> bool:
        stmt = select(PassportShareView.id).where(
            PassportShareView.share_id == share_id,
            PassportShareView.viewer_ip_hash == viewer_ip_hash,
            PassportShareView.user_agent == user_agent,
            PassportShareView.created_at >= cutoff,
        ).limit(1)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def count_total_for_share(self, share_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(PassportShareView)
            .where(PassportShareView.share_id == share_id)
        )
        return int((await self._session.execute(stmt)).scalar_one() or 0)

    async def count_unique_for_share(self, share_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(PassportShareView)
            .where(
                PassportShareView.share_id == share_id,
                PassportShareView.is_unique_view.is_(True),
            )
        )
        return int((await self._session.execute(stmt)).scalar_one() or 0)

    async def list_recent_for_share(self, share_id: UUID, *, limit: int) -> list[PassportShareView]:
        stmt = (
            select(PassportShareView)
            .where(PassportShareView.share_id == share_id)
            .order_by(PassportShareView.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())
