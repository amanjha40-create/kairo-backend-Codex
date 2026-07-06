"""Repository for Trust Passport share links."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.passport_share_link import PassportShareLink


class PassportShareRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, share_id: UUID) -> PassportShareLink | None:
        stmt = select(PassportShareLink).where(PassportShareLink.id == share_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(self, link: PassportShareLink) -> PassportShareLink:
        self._session.add(link)
        await self._session.flush()
        return link

    async def get_owned(self, share_id: UUID, owner_user_id: UUID) -> PassportShareLink | None:
        stmt = select(PassportShareLink).where(
            PassportShareLink.id == share_id,
            PassportShareLink.owner_user_id == owner_user_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_token_hash(self, token_hash: str) -> PassportShareLink | None:
        stmt = select(PassportShareLink).where(PassportShareLink.token_hash == token_hash)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_owner(
        self,
        owner_user_id: UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[PassportShareLink], int]:
        base_filter = (PassportShareLink.owner_user_id == owner_user_id,)
        count_stmt = select(func.count()).select_from(PassportShareLink).where(*base_filter)
        total = int((await self._session.execute(count_stmt)).scalar_one())

        list_stmt = (
            select(PassportShareLink)
            .where(*base_filter)
            .order_by(PassportShareLink.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = list((await self._session.execute(list_stmt)).scalars().all())
        return rows, total
