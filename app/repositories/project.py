"""Repository for candidate projects."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(self, user_id: UUID) -> list[Project]:
        stmt = select(Project).where(Project.user_id == user_id, Project.deleted_at.is_(None)).order_by(Project.is_ongoing.desc(), Project.start_date.desc().nullslast(), Project.created_at.desc())
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_owned(self, project_id: UUID, user_id: UUID) -> Project | None:
        stmt = select(Project).where(Project.id == project_id, Project.user_id == user_id, Project.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def soft_delete(self, project: Project) -> None:
        project.deleted_at = datetime.now(tz=UTC)
        await self._session.flush()
