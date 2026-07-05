"""Employment document persistence — scoped lists, batch reads, soft delete."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.employment_document import EmploymentDocument
from app.repositories.base import BaseRepository
from app.repositories.criteria import EmploymentDocumentSortField, SortOrder


class EmploymentDocumentRepository(BaseRepository[EmploymentDocument]):
    """Document lookup scoped to employment — ownership enforced in services."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, EmploymentDocument)

    def _active_scope(self, stmt: Select[tuple[EmploymentDocument]]) -> Select[tuple[EmploymentDocument]]:
        return stmt.where(EmploymentDocument.deleted_at.is_(None))

    def _order_column(self, sort_by: EmploymentDocumentSortField):
        return {
            EmploymentDocumentSortField.CREATED_AT: EmploymentDocument.created_at,
            EmploymentDocumentSortField.UPDATED_AT: EmploymentDocument.updated_at,
            EmploymentDocumentSortField.BYTE_SIZE: EmploymentDocument.byte_size,
        }[sort_by]

    async def create(self, entity: EmploymentDocument) -> EmploymentDocument:
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def update(self, entity: EmploymentDocument) -> EmploymentDocument:
        await self._session.flush()
        return entity

    async def get_by_id(self, document_id: UUID, *, include_deleted: bool = False) -> EmploymentDocument | None:
        stmt = select(EmploymentDocument).where(EmploymentDocument.id == document_id)
        if not include_deleted:
            stmt = stmt.where(EmploymentDocument.deleted_at.is_(None))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_by_id(self, document_id: UUID) -> EmploymentDocument | None:
        return await self.get_by_id(document_id, include_deleted=False)

    async def list_all_active_for_employment(self, employment_id: UUID) -> list[EmploymentDocument]:
        stmt = self._active_scope(
            select(EmploymentDocument)
            .where(EmploymentDocument.employment_id == employment_id)
            .order_by(EmploymentDocument.created_at.asc()),
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())

    async def get_active_for_employment(
        self,
        employment_id: UUID,
        document_id: UUID,
    ) -> EmploymentDocument | None:
        stmt = self._active_scope(
            select(EmploymentDocument).where(
                EmploymentDocument.employment_id == employment_id,
                EmploymentDocument.id == document_id,
            ),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_by_id_with_employment(self, document_id: UUID) -> EmploymentDocument | None:
        """Load document plus parent employment row (joinedload for single round-trip)."""

        stmt = (
            select(EmploymentDocument)
            .where(EmploymentDocument.id == document_id, EmploymentDocument.deleted_at.is_(None))
            .options(joinedload(EmploymentDocument.employment))
        )
        result = await self._session.execute(stmt)
        return result.unique().scalar_one_or_none()

    async def get_active_by_object_key(self, object_key: str) -> EmploymentDocument | None:
        stmt = self._active_scope(
            select(EmploymentDocument).where(EmploymentDocument.object_key == object_key),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_many_by_ids(self, document_ids: list[UUID]) -> list[EmploymentDocument]:
        """Batch fetch active documents — preserves caller iteration order not guaranteed."""

        if not document_ids:
            return []
        stmt = select(EmploymentDocument).where(
            EmploymentDocument.id.in_(document_ids),
            EmploymentDocument.deleted_at.is_(None),
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())

    async def soft_delete(self, document_id: UUID) -> bool:
        row = await self.get_active_by_id(document_id)
        if row is None:
            return False
        row.deleted_at = datetime.now(tz=UTC)
        await self._session.flush()
        return True

    async def soft_delete_batch(self, document_ids: list[UUID]) -> int:
        if not document_ids:
            return 0
        now = datetime.now(tz=UTC)
        stmt = (
            update(EmploymentDocument)
            .where(EmploymentDocument.id.in_(document_ids), EmploymentDocument.deleted_at.is_(None))
            .values(deleted_at=now)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return int(result.rowcount or 0)

    async def list(
        self,
        *,
        employment_id: UUID,
        offset: int,
        limit: int,
        extraction_statuses: list[str] | None = None,
        document_types: list[str] | None = None,
        sort_by: EmploymentDocumentSortField = EmploymentDocumentSortField.CREATED_AT,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> tuple[list[EmploymentDocument], int]:
        """Paginated documents for one employment case — requires `employment_id` scope."""

        return await self.list_for_employment(
            employment_id,
            offset=offset,
            limit=limit,
            extraction_statuses=extraction_statuses,
            document_types=document_types,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def list_for_employment(
        self,
        employment_id: UUID,
        *,
        offset: int,
        limit: int,
        extraction_statuses: list[str] | None = None,
        document_types: list[str] | None = None,
        sort_by: EmploymentDocumentSortField = EmploymentDocumentSortField.CREATED_AT,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> tuple[list[EmploymentDocument], int]:
        filters = [
            EmploymentDocument.employment_id == employment_id,
            EmploymentDocument.deleted_at.is_(None),
        ]
        if extraction_statuses:
            filters.append(EmploymentDocument.extraction_status.in_(extraction_statuses))
        if document_types:
            filters.append(EmploymentDocument.document_type.in_(document_types))

        base = and_(*filters)
        count_stmt = select(func.count()).select_from(EmploymentDocument).where(base)
        total = int((await self._session.execute(count_stmt)).scalar_one())

        col = self._order_column(sort_by)
        order_expr = col.desc() if sort_order == SortOrder.DESC else col.asc()

        stmt = (
            select(EmploymentDocument)
            .where(base)
            .order_by(order_expr)
            .offset(offset)
            .limit(limit)
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all()), total

    async def get_documents_by_employment(
        self,
        employment_id: UUID,
        *,
        offset: int,
        limit: int,
        extraction_statuses: list[str] | None = None,
        document_types: list[str] | None = None,
        sort_by: EmploymentDocumentSortField = EmploymentDocumentSortField.CREATED_AT,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> tuple[list[EmploymentDocument], int]:
        """Alias for paginated document listing under a case."""

        return await self.list_for_employment(
            employment_id,
            offset=offset,
            limit=limit,
            extraction_statuses=extraction_statuses,
            document_types=document_types,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def count_other_active_with_checksum(
        self,
        employment_id: UUID,
        checksum_sha256: str,
        *,
        exclude_document_id: UUID | None = None,
    ) -> int:
        """Other active rows under the same case sharing a finalized digest (dedup gate)."""

        filters = [
            EmploymentDocument.employment_id == employment_id,
            EmploymentDocument.deleted_at.is_(None),
            EmploymentDocument.checksum_sha256 == checksum_sha256,
        ]
        if exclude_document_id is not None:
            filters.append(EmploymentDocument.id != exclude_document_id)
        base = and_(*filters)
        stmt = select(func.count()).select_from(EmploymentDocument).where(base)
        return int((await self._session.execute(stmt)).scalar_one())

    async def count_pending_intent_duplicate(
        self,
        employment_id: UUID,
        *,
        document_type: str,
        original_filename: str,
        pending_checksum_hex: str,
    ) -> int:
        """In-flight upload intents sharing type + filename (sentinel checksum)."""

        base = and_(
            EmploymentDocument.employment_id == employment_id,
            EmploymentDocument.deleted_at.is_(None),
            EmploymentDocument.document_type == document_type,
            EmploymentDocument.original_filename == original_filename,
            EmploymentDocument.checksum_sha256 == pending_checksum_hex,
        )
        stmt = select(func.count()).select_from(EmploymentDocument).where(base)
        return int((await self._session.execute(stmt)).scalar_one())

    async def count_busy_extractions_for_employment_excluding(
        self,
        employment_id: UUID,
        *,
        exclude_document_id: UUID,
        busy_statuses: Sequence[str],
    ) -> int:
        """Serialized extraction — QUEUED/PROCESSING elsewhere on the same case."""

        base = and_(
            EmploymentDocument.employment_id == employment_id,
            EmploymentDocument.deleted_at.is_(None),
            EmploymentDocument.id != exclude_document_id,
            EmploymentDocument.extraction_status.in_(tuple(busy_statuses)),
        )
        stmt = select(func.count()).select_from(EmploymentDocument).where(base)
        return int((await self._session.execute(stmt)).scalar_one())

    async def soft_delete_all_for_employment(self, employment_id: UUID) -> int:
        """Bulk soft-delete evidence rows for a case (e.g. applicant deletes draft)."""

        now = datetime.now(tz=UTC)
        stmt = (
            update(EmploymentDocument)
            .where(
                EmploymentDocument.employment_id == employment_id,
                EmploymentDocument.deleted_at.is_(None),
            )
            .values(deleted_at=now)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return int(result.rowcount or 0)

    async def count_active_for_employment(self, employment_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(EmploymentDocument)
            .where(
                EmploymentDocument.employment_id == employment_id,
                EmploymentDocument.deleted_at.is_(None),
            )
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def count_completed_for_employment(self, employment_id: UUID, *, pending_checksum_hex: str) -> int:
        """Active rows with a finalized S3 upload (not pending intent sentinel)."""

        stmt = (
            select(func.count())
            .select_from(EmploymentDocument)
            .where(
                EmploymentDocument.employment_id == employment_id,
                EmploymentDocument.deleted_at.is_(None),
                EmploymentDocument.checksum_sha256 != pending_checksum_hex,
            )
        )
        return int((await self._session.execute(stmt)).scalar_one())
