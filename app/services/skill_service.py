"""Candidate skill CRUD."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError
from app.models.skill import Skill
from app.repositories.skill import SkillRepository
from app.schemas.skill import SkillCreateRequest


class SkillService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SkillRepository(session)

    async def list_for_user(self, user_id: UUID) -> list[Skill]:
        return await self._repo.list_for_user(user_id)

    async def create(self, user_id: UUID, payload: SkillCreateRequest) -> Skill:
        normalized = payload.name.casefold()
        if await self._repo.get_by_normalized_name(user_id, normalized):
            raise ConflictError("This skill has already been added")
        item = Skill(user_id=user_id, name=payload.name, normalized_name=normalized, verification_status="self_declared")
        self._session.add(item)
        await self._session.commit()
        await self._session.refresh(item)
        return item

    async def delete(self, user_id: UUID, skill_id: UUID) -> None:
        item = await self._repo.get_owned(skill_id, user_id)
        if item is None:
            raise NotFoundError("Skill not found")
        await self._repo.soft_delete(item)
        await self._session.commit()
