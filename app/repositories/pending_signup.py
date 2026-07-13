"""Pending signup repository — staged registration before email verification."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PendingSignup
from app.repositories.base import BaseRepository


class PendingSignupRepository(BaseRepository[PendingSignup]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PendingSignup)

    async def get_by_id(self, signup_id: UUID) -> PendingSignup | None:
        stmt = select(PendingSignup).where(PendingSignup.id == signup_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> PendingSignup | None:
        stmt = select(PendingSignup).where(PendingSignup.email == email)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> PendingSignup | None:
        stmt = select(PendingSignup).where(PendingSignup.phone == phone)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_by_email(self, email: str) -> None:
        await self._session.execute(delete(PendingSignup).where(PendingSignup.email == email))

    async def delete_by_phone(self, phone: str) -> None:
        await self._session.execute(delete(PendingSignup).where(PendingSignup.phone == phone))

    async def delete_by_id(self, signup_id: UUID) -> None:
        await self._session.execute(delete(PendingSignup).where(PendingSignup.id == signup_id))

    async def is_expired(self, row: PendingSignup) -> bool:
        return row.expires_at <= datetime.now(tz=UTC)
