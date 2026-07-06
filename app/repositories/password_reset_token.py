"""Password reset token persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.password_reset_token import PasswordResetToken
from app.repositories.base import BaseRepository


class PasswordResetTokenRepository(BaseRepository[PasswordResetToken]):
    """Data access for one-time password reset tokens."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PasswordResetToken)

    async def create(self, token: PasswordResetToken) -> PasswordResetToken:
        self._session.add(token)
        await self._session.flush()
        return token

    async def get_active_by_hash(self, token_hash: str, *, now: datetime) -> PasswordResetToken | None:
        stmt = select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def mark_used(self, token_id: UUID, *, used_at: datetime) -> None:
        await self._session.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.id == token_id)
            .values(used_at=used_at)
        )

    async def mark_all_active_for_user_used(self, user_id: UUID, *, used_at: datetime) -> None:
        await self._session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.used_at.is_(None),
            )
            .values(used_at=used_at)
        )

    async def delete_expired_before(self, cutoff: datetime) -> int:
        stmt = delete(PasswordResetToken).where(PasswordResetToken.expires_at < cutoff)
        result = await self._session.execute(stmt)
        return int(result.rowcount or 0)
