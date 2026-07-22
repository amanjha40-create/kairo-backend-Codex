"""Candidate project CRUD."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.project import Project
from app.repositories.project import ProjectRepository
from app.schemas.project import ProjectCreateRequest, ProjectUpdateRequest


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = ProjectRepository(session)

    async def list_for_user(self, user_id: UUID) -> list[Project]:
        return await self._repo.list_for_user(user_id)

    async def get_owned(self, user_id: UUID, project_id: UUID) -> Project:
        item = await self._repo.get_owned(project_id, user_id)
        if item is None:
            raise NotFoundError("Project not found")
        return item

    async def create(self, user_id: UUID, payload: ProjectCreateRequest) -> Project:
        data = payload.model_dump()
        for key in ("project_url", "repository_url"):
            if data[key] is not None:
                data[key] = str(data[key])
        item = Project(user_id=user_id, **data, verification_status="self_declared")
        self._session.add(item)
        await self._session.commit()
        await self._session.refresh(item)
        return item

    async def update(self, user_id: UUID, project_id: UUID, payload: ProjectUpdateRequest) -> Project:
        item = await self.get_owned(user_id, project_id)
        data = payload.model_dump(exclude_unset=True)
        for key in ("project_url", "repository_url"):
            if key in data and data[key] is not None:
                data[key] = str(data[key])
        for key, value in data.items():
            setattr(item, key, value)
        await self._session.commit()
        await self._session.refresh(item)
        return item

    async def delete(self, user_id: UUID, project_id: UUID) -> None:
        item = await self.get_owned(user_id, project_id)
        await self._repo.soft_delete(item)
        await self._session.commit()
