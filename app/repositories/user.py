"""User repository — queries scoped for soft-delete safety."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Persistence operations for `User` — soft-delete aware lookups."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)

    async def get_by_id(self, obj_id: UUID) -> User | None:
        stmt = select(User).where(User.id == obj_id, User.deleted_at.is_(None))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_google_id(self, google_id: str) -> User | None:
        stmt = select(User).where(User.google_id == google_id, User.deleted_at.is_(None))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email, User.deleted_at.is_(None))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> User | None:
        stmt = select(User).where(User.phone == phone, User.deleted_at.is_(None))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_non_deleted(
        self,
        *,
        offset: int,
        limit: int,
        order_by=User.created_at,
    ) -> tuple[list[User], int]:
        """Paginate active users (`deleted_at IS NULL`)."""

        return await self.list_page(
            offset=offset,
            limit=limit,
            base_filters=[User.deleted_at.is_(None)],
            order_by=order_by,
        )

    async def mark_employment_onboarding_completed_if_needed(self, user_id: UUID) -> None:
        """Set timestamp once when the user saves their first employment case (job-history onboarding)."""

        user = await self.get_by_id(user_id)
        if user is None or user.employment_onboarding_completed_at is not None:
            return
        user.employment_onboarding_completed_at = datetime.now(tz=UTC)
        await self._session.flush()
