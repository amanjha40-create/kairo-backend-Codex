"""Repository for education records and education documents."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Education, EducationDocument


class EducationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, edu: Education) -> Education:
        self._session.add(edu)
        await self._session.flush()
        return edu

    async def get_owned(self, education_id: UUID, user_id: UUID) -> Education | None:
        stmt = select(Education).where(
            Education.id == education_id,
            Education.user_id == user_id,
            Education.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Education], int]:
        base_filter = (
            Education.user_id == user_id,
            Education.deleted_at.is_(None),
        )
        count_stmt = select(func.count()).select_from(Education).where(*base_filter)
        total = int((await self._session.execute(count_stmt)).scalar_one())

        list_stmt = (
            select(Education)
            .where(*base_filter)
            .order_by(Education.start_date.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = list((await self._session.execute(list_stmt)).scalars().all())
        return rows, total

    async def soft_delete(self, edu: Education) -> None:
        edu.deleted_at = datetime.now(tz=UTC)
        await self._session.flush()


class EducationDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, doc: EducationDocument) -> EducationDocument:
        self._session.add(doc)
        await self._session.flush()
        return doc

    async def get_for_education(
        self, document_id: UUID, education_id: UUID,
    ) -> EducationDocument | None:
        stmt = select(EducationDocument).where(
            EducationDocument.id == document_id,
            EducationDocument.education_id == education_id,
            EducationDocument.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_education(
        self,
        education_id: UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[EducationDocument], int]:
        base_filter = (
            EducationDocument.education_id == education_id,
            EducationDocument.deleted_at.is_(None),
        )
        count_stmt = select(func.count()).select_from(EducationDocument).where(*base_filter)
        total = int((await self._session.execute(count_stmt)).scalar_one())

        list_stmt = (
            select(EducationDocument)
            .where(*base_filter)
            .order_by(EducationDocument.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = list((await self._session.execute(list_stmt)).scalars().all())
        return rows, total

    async def soft_delete(self, doc: EducationDocument) -> None:
        doc.deleted_at = datetime.now(tz=UTC)
        await self._session.flush()
