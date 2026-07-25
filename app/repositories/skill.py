"""Repository for candidate skills."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import Skill


class SkillRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(self, user_id: UUID) -> list[Skill]:
        stmt = select(Skill).where(Skill.user_id == user_id, Skill.deleted_at.is_(None)).order_by(func.lower(Skill.name))
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_owned(self, skill_id: UUID, user_id: UUID) -> Skill | None:
        stmt = select(Skill).where(Skill.id == skill_id, Skill.user_id == user_id, Skill.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_normalized_name(self, user_id: UUID, name: str) -> Skill | None:
        stmt = select(Skill).where(Skill.user_id == user_id, Skill.normalized_name == name, Skill.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def soft_delete(self, skill: Skill) -> None:
        skill.deleted_at = datetime.now(tz=UTC)
        await self._session.flush()
