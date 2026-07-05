"""Verification workflow and immutable audit stream — single repository surface."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.employment.enums import VerificationStatus
from app.models.employment import Employment
from app.models.verification_audit import VerificationAuditEvent


# Default reviewer-queue slice — cases waiting on internal review.
_DEFAULT_PENDING_STATUSES: tuple[str, ...] = (
    VerificationStatus.SUBMITTED.value,
    VerificationStatus.UNDER_REVIEW.value,
)


class VerificationRepository:
    """Pending-case queries plus append-only audit persistence (no updates/deletes on audit rows)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        *,
        employment_id: UUID,
        actor_user_id: UUID | None,
        action: str,
        previous_status: str | None,
        new_status: str | None,
        metadata_payload: dict[str, Any] | None,
        actor_role: str | None = None,
        actor_display_name: str | None = None,
    ) -> VerificationAuditEvent:
        """Append an audit event — caller owns transaction boundaries (commit/rollback).

        actor_role and actor_display_name are snapshots from the time of the action
        (so promotions/deletions don't rewrite history).
        """

        # Auto-snapshot actor role/name from the users table if not explicitly provided
        if actor_user_id and (actor_role is None or actor_display_name is None):
            from app.models import User
            user = await self._session.get(User, actor_user_id)
            if user:
                actor_role = actor_role or user.role
                actor_display_name = actor_display_name or (user.full_name or user.email)

        row = VerificationAuditEvent(
            employment_id=employment_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            actor_display_name=actor_display_name,
            action=action,
            previous_status=previous_status,
            new_status=new_status,
            metadata_payload=metadata_payload,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_for_employment(
        self,
        employment_id: UUID,
        *,
        offset: int,
        limit: int,
        order: Literal["asc", "desc"] = "asc",
    ) -> tuple[list[VerificationAuditEvent], int]:
        """Paginated audit trail for a case."""

        count_stmt = (
            select(func.count())
            .select_from(VerificationAuditEvent)
            .where(VerificationAuditEvent.employment_id == employment_id)
        )
        total = int((await self._session.execute(count_stmt)).scalar_one())

        ord_expr = (
            VerificationAuditEvent.created_at.asc()
            if order == "asc"
            else VerificationAuditEvent.created_at.desc()
        )
        stmt = (
            select(VerificationAuditEvent)
            .where(VerificationAuditEvent.employment_id == employment_id)
            .order_by(ord_expr)
            .offset(offset)
            .limit(limit)
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all()), total

    async def get_pending_verifications(
        self,
        *,
        offset: int,
        limit: int,
        statuses: list[str] | None = None,
        employer_ilike: str | None = None,
        submitted_after: date | None = None,
        submitted_before: date | None = None,
    ) -> tuple[list[Employment], int]:
        """Employments in reviewer-actionable states (default: submitted + under_review)."""

        pending_statuses = tuple(statuses) if statuses else _DEFAULT_PENDING_STATUSES
        filters = [
            Employment.deleted_at.is_(None),
            Employment.verification_status.in_(pending_statuses),
        ]
        if employer_ilike:
            pattern = f"%{employer_ilike.strip()}%"
            filters.append(
                or_(
                    Employment.employer_legal_name.ilike(pattern),
                    Employment.employer_trade_name.ilike(pattern),
                ),
            )
        if submitted_after is not None:
            start = datetime.combine(submitted_after, time.min, tzinfo=UTC)
            filters.append(Employment.submitted_at >= start)
        if submitted_before is not None:
            end = datetime.combine(submitted_before, time.max, tzinfo=UTC)
            filters.append(Employment.submitted_at <= end)

        base = and_(*filters)

        count_stmt = select(func.count()).select_from(Employment).where(base)
        total = int((await self._session.execute(count_stmt)).scalar_one())

        stmt = (
            select(Employment)
            .where(base)
            .order_by(Employment.submitted_at.asc().nulls_last(), Employment.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all()), total
