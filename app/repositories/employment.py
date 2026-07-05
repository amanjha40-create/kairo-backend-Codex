"""Employment case persistence — scoped queries, pagination, sorting, eager loads."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, with_loader_criteria

from app.models.employment import Employment
from app.models.employment_document import EmploymentDocument
from app.repositories.base import BaseRepository
from app.repositories.criteria import EmploymentSortField, SortOrder


class EmploymentRepository(BaseRepository[Employment]):
    """Query helpers optimized for indexed filters (`verification_status`, dates, employer name)."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Employment)

    def _active_scope(self, stmt: Select[tuple[Employment]]) -> Select[tuple[Employment]]:
        return stmt.where(Employment.deleted_at.is_(None))

    def _order_by_clause(self, *, sort_by: EmploymentSortField, order: SortOrder):
        col = {
            EmploymentSortField.CREATED_AT: Employment.created_at,
            EmploymentSortField.UPDATED_AT: Employment.updated_at,
            EmploymentSortField.SUBMITTED_AT: Employment.submitted_at,
        }[sort_by]
        expr = col.desc() if order == SortOrder.DESC else col.asc()
        if sort_by == EmploymentSortField.SUBMITTED_AT:
            expr = expr.nulls_last() if order == SortOrder.DESC else expr.nulls_first()
        return expr

    async def create(self, entity: Employment) -> Employment:
        """Persist a new row — caller typically commits on the session."""

        self._session.add(entity)
        await self._session.flush()
        return entity

    async def update(self, entity: Employment) -> Employment:
        """Flush ORM mutations already applied to `entity`."""

        await self._session.flush()
        return entity

    async def get_by_id(self, employment_id: UUID, *, include_deleted: bool = False) -> Employment | None:
        """Primary key lookup — defaults to active rows only."""

        stmt = select(Employment).where(Employment.id == employment_id)
        if not include_deleted:
            stmt = stmt.where(Employment.deleted_at.is_(None))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_by_id(self, employment_id: UUID) -> Employment | None:
        return await self.get_by_id(employment_id, include_deleted=False)

    async def get_active_by_id_with_documents(self, employment_id: UUID) -> Employment | None:
        """Single-case fetch with active documents only (soft-deleted docs excluded)."""

        stmt = (
            select(Employment)
            .where(Employment.id == employment_id, Employment.deleted_at.is_(None))
            .options(
                selectinload(Employment.documents),
                with_loader_criteria(
                    EmploymentDocument,
                    EmploymentDocument.deleted_at.is_(None),
                    include_aliases=True,
                ),
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_owned_active(self, employment_id: UUID, owner_user_id: UUID) -> Employment | None:
        stmt = self._active_scope(
            select(Employment).where(
                Employment.id == employment_id,
                Employment.created_by_user_id == owner_user_id,
            ),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_owned_active_for_update(self, employment_id: UUID, owner_user_id: UUID) -> Employment | None:
        """Same as `get_owned_active` but acquires a row-level lock (SELECT FOR UPDATE).

        Use before any state-machine transition to serialise concurrent requests
        and prevent double-submission races.
        """

        stmt = self._active_scope(
            select(Employment)
            .where(
                Employment.id == employment_id,
                Employment.created_by_user_id == owner_user_id,
            )
            .with_for_update(),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_owned_active_with_employer_request(
        self,
        employment_id: UUID,
        owner_user_id: UUID,
    ) -> Employment | None:
        stmt = self._active_scope(
            select(Employment)
            .where(
                Employment.id == employment_id,
                Employment.created_by_user_id == owner_user_id,
            )
            .options(selectinload(Employment.employer_verification_request)),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def soft_delete(self, employment_id: UUID) -> bool:
        """Set `deleted_at` — returns False when already deleted or missing."""

        row = await self.get_active_by_id(employment_id)
        if row is None:
            return False
        row.deleted_at = datetime.now(tz=UTC)
        await self._session.flush()
        return True

    async def soft_delete_batch(self, employment_ids: list[UUID]) -> int:
        """Bulk soft-delete — returns affected row count."""

        if not employment_ids:
            return 0
        now = datetime.now(tz=UTC)
        stmt = (
            update(Employment)
            .where(Employment.id.in_(employment_ids), Employment.deleted_at.is_(None))
            .values(deleted_at=now)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return int(result.rowcount or 0)

    async def list(
        self,
        *,
        offset: int,
        limit: int,
        owner_user_id: UUID | None = None,
        statuses: list[str] | None = None,
        employer_ilike: str | None = None,
        submitted_after: date | None = None,
        submitted_before: date | None = None,
        created_after: date | None = None,
        created_before: date | None = None,
        sort_by: EmploymentSortField = EmploymentSortField.UPDATED_AT,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> tuple[list[Employment], int]:
        """Paginated listing — applicant scope when `owner_user_id` is set; otherwise admin (created_* dates)."""

        filters = [Employment.deleted_at.is_(None)]

        if owner_user_id is not None:
            filters.append(Employment.created_by_user_id == owner_user_id)

        if statuses:
            filters.append(Employment.verification_status.in_(statuses))

        if employer_ilike:
            pattern = f"%{employer_ilike.strip()}%"
            filters.append(
                or_(
                    Employment.employer_legal_name.ilike(pattern),
                    Employment.employer_trade_name.ilike(pattern),
                ),
            )

        if owner_user_id is not None:
            if submitted_after is not None:
                start = datetime.combine(submitted_after, time.min, tzinfo=UTC)
                filters.append(Employment.submitted_at >= start)
            if submitted_before is not None:
                end = datetime.combine(submitted_before, time.max, tzinfo=UTC)
                filters.append(Employment.submitted_at <= end)
        else:
            if created_after is not None:
                ca = datetime.combine(created_after, time.min, tzinfo=UTC)
                filters.append(Employment.created_at >= ca)
            if created_before is not None:
                cb = datetime.combine(created_before, time.max, tzinfo=UTC)
                filters.append(Employment.created_at <= cb)

        base = and_(*filters)
        count_stmt = select(func.count()).select_from(Employment).where(base)
        total = int((await self._session.execute(count_stmt)).scalar_one())

        order_expr = self._order_by_clause(sort_by=sort_by, order=sort_order)
        stmt = (
            select(Employment)
            .where(base)
            .order_by(order_expr)
            .offset(offset)
            .limit(limit)
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all()), total

    async def list_for_owner(
        self,
        owner_user_id: UUID,
        *,
        offset: int,
        limit: int,
        statuses: list[str] | None = None,
        employer_ilike: str | None = None,
        submitted_after: date | None = None,
        submitted_before: date | None = None,
        sort_by: EmploymentSortField = EmploymentSortField.UPDATED_AT,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> tuple[list[Employment], int]:
        return await self.list(
            offset=offset,
            limit=limit,
            owner_user_id=owner_user_id,
            statuses=statuses,
            employer_ilike=employer_ilike,
            submitted_after=submitted_after,
            submitted_before=submitted_before,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def get_user_employments(
        self,
        owner_user_id: UUID,
        *,
        offset: int,
        limit: int,
        statuses: list[str] | None = None,
        employer_ilike: str | None = None,
        submitted_after: date | None = None,
        submitted_before: date | None = None,
        sort_by: EmploymentSortField = EmploymentSortField.UPDATED_AT,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> tuple[list[Employment], int]:
        """Alias for applicant-scoped listing (`list_for_owner`)."""

        return await self.list_for_owner(
            owner_user_id,
            offset=offset,
            limit=limit,
            statuses=statuses,
            employer_ilike=employer_ilike,
            submitted_after=submitted_after,
            submitted_before=submitted_before,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def list_admin(
        self,
        *,
        offset: int,
        limit: int,
        statuses: list[str] | None = None,
        employer_ilike: str | None = None,
        created_after: date | None = None,
        created_before: date | None = None,
        sort_by: EmploymentSortField = EmploymentSortField.UPDATED_AT,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> tuple[list[Employment], int]:
        return await self.list(
            offset=offset,
            limit=limit,
            owner_user_id=None,
            statuses=statuses,
            employer_ilike=employer_ilike,
            created_after=created_after,
            created_before=created_before,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def count_owner_pipeline_excluding(
        self,
        owner_user_id: UUID,
        *,
        exclude_employment_id: UUID,
        pipeline_statuses: tuple[str, ...],
    ) -> int:
        """Count other non-deleted cases for this owner in active reviewer pipeline states."""

        base = and_(
            Employment.deleted_at.is_(None),
            Employment.created_by_user_id == owner_user_id,
            Employment.id != exclude_employment_id,
            Employment.verification_status.in_(pipeline_statuses),
        )
        stmt = select(func.count()).select_from(Employment).where(base)
        return int((await self._session.execute(stmt)).scalar_one())
