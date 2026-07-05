"""Repository for user_social_accounts — linked OAuth provider rows."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_social_account import UserSocialAccount
from app.repositories.base import BaseRepository


class UserSocialAccountRepository(BaseRepository[UserSocialAccount]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, UserSocialAccount)

    async def get_by_provider(self, provider: str, provider_user_id: str) -> UserSocialAccount | None:
        """Find a linked account by provider name + provider's user ID."""

        stmt = select(UserSocialAccount).where(
            UserSocialAccount.provider == provider,
            UserSocialAccount.provider_user_id == provider_user_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_user_and_provider(self, user_id: UUID, provider: str) -> UserSocialAccount | None:
        """Check if a user already has a specific provider linked."""

        stmt = select(UserSocialAccount).where(
            UserSocialAccount.user_id == user_id,
            UserSocialAccount.provider == provider,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: UUID) -> list[UserSocialAccount]:
        """All linked providers for a user."""

        stmt = select(UserSocialAccount).where(UserSocialAccount.user_id == user_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, account: UserSocialAccount) -> UserSocialAccount:
        self._session.add(account)
        await self._session.flush()
        return account

    async def delete(self, account: UserSocialAccount) -> None:
        await self._session.delete(account)
        await self._session.flush()
