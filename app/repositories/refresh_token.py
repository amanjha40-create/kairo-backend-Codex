"""Refresh token persistence — rotation and revocation helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RefreshToken
from app.repositories.base import BaseRepository


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    """Opaque refresh token rows keyed by SHA-256 hash."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, RefreshToken)

    async def get_by_hash_any(self, token_hash: str) -> RefreshToken | None:
        """Include revoked rows — used to detect refresh-token reuse attacks."""

        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_valid_by_hash(self, token_hash: str) -> RefreshToken | None:
        stmt = select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > datetime.now(tz=UTC),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke(self, token_id: UUID) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.id == token_id)
            .values(revoked_at=datetime.now(tz=UTC)),
        )

    async def revoke_family(self, family_id: UUID) -> None:
        """Reuse attack mitigation — invalidate all tokens in a rotation family."""

        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(tz=UTC)),
        )

    async def revoke_all_for_user(self, user_id: UUID) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(tz=UTC)),
        )

    async def delete_expired_before(self, cutoff: datetime) -> int:
        """Remove rows with `expires_at` strictly before `cutoff` (e.g. scheduled cleanup)."""

        stmt = delete(RefreshToken).where(RefreshToken.expires_at < cutoff)
        result = await self._session.execute(stmt)
        return int(result.rowcount or 0)
