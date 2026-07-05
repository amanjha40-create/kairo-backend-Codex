"""Repository for user identity documents."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserDocument


class UserDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, doc: UserDocument) -> UserDocument:
        self._session.add(doc)
        await self._session.flush()
        return doc

    async def get_owned(self, document_id: UUID, user_id: UUID) -> UserDocument | None:
        stmt = select(UserDocument).where(
            UserDocument.id == document_id,
            UserDocument.user_id == user_id,
            UserDocument.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[UserDocument], int]:
        base_filter = (
            UserDocument.user_id == user_id,
            UserDocument.deleted_at.is_(None),
        )
        count_stmt = select(func.count()).select_from(UserDocument).where(*base_filter)
        total = int((await self._session.execute(count_stmt)).scalar_one())

        list_stmt = (
            select(UserDocument)
            .where(*base_filter)
            .order_by(UserDocument.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = list((await self._session.execute(list_stmt)).scalars().all())
        return rows, total

    async def soft_delete(self, doc: UserDocument) -> None:
        doc.deleted_at = datetime.now(tz=UTC)
        await self._session.flush()
