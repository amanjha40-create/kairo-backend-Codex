"""Backend-truth overview aggregation for the Admin Portal."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.organization import Organization
from app.models.trust_registry_record import TrustRegistryRecord
from app.models.user import User
from app.models.verification_request import VerificationRequest
from app.models.verification_request_event import VerificationRequestEvent
from app.schemas.admin_overview import (
    AdminOverviewActivity,
    AdminOverviewCase,
    AdminOverviewResponse,
)
from app.verification_requests.enums import (
    VerificationRequestEventSource,
    VerificationRequestStatus,
)

_PENDING_REVIEW_STATUSES = {
    VerificationRequestStatus.PENDING_ADMIN_REVIEW,
    VerificationRequestStatus.PENDING_ADMIN_RE_REVIEW,
}
_PRIORITY_VALUES = {"high", "urgent"}
_RECENT_CASE_LIMIT = 10
_RECENT_ACTIVITY_LIMIT = 10


class AdminOverviewService:
    """Aggregate bounded, existing data sources without creating a metrics store."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_overview(self, *, recent_window_days: int = 30) -> AdminOverviewResponse:
        now = datetime.now(UTC)
        window_start = now - timedelta(days=recent_window_days)

        total, status_counts = await self._request_counts()
        pending_review_count = await self._count_requests(statuses=_PENDING_REVIEW_STATUSES)
        priority_case_count = await self._count_priority_cases()
        recent_cases = await self._recent_cases(window_start)
        recent_activity = await self._recent_admin_activity(window_start)
        organization_total = await self._count(Organization)
        registry_total = await self._count(
            TrustRegistryRecord,
            TrustRegistryRecord.deleted_at.is_(None),
        )
        user_total = await self._count(User, User.deleted_at.is_(None))

        return AdminOverviewResponse(
            generated_at=now,
            recent_window_days=recent_window_days,
            total_verification_requests=total,
            requests_by_status=status_counts,
            pending_review_count=pending_review_count,
            priority_case_count=priority_case_count,
            recent_cases=recent_cases,
            recent_admin_activity=recent_activity,
            organization_total=organization_total,
            registry_total=registry_total,
            user_total=user_total,
        )

    async def _request_counts(self) -> tuple[int, dict[str, int]]:
        stmt = select(VerificationRequest.status, func.count()).group_by(VerificationRequest.status)
        rows = (await self._session.execute(stmt)).all()
        counts: dict[str, int] = {}
        for status, count in rows:
            counts[str(status.value if hasattr(status, "value") else status)] = int(count)
        return sum(counts.values()), dict(sorted(counts.items()))

    async def _count_requests(self, *, statuses: set[VerificationRequestStatus]) -> int:
        return await self._count(VerificationRequest, VerificationRequest.status.in_(statuses))

    async def _count_priority_cases(self) -> int:
        return await self._count(
            VerificationRequest,
            VerificationRequest.priority.in_(_PRIORITY_VALUES),
        )

    async def _recent_cases(self, window_start: datetime) -> list[AdminOverviewCase]:
        stmt = (
            select(VerificationRequest)
            .options(joinedload(VerificationRequest.organization))
            .where(VerificationRequest.created_at >= window_start)
            .order_by(VerificationRequest.created_at.desc())
            .limit(_RECENT_CASE_LIMIT)
        )
        requests = list((await self._session.execute(stmt)).scalars().unique().all())
        return [
            AdminOverviewCase(
                public_id=request.public_id,
                subject_name=request.subject_name,
                organization_name=request.organization.name if request.organization else None,
                status=(
                    request.status.value
                    if hasattr(request.status, "value")
                    else str(request.status)
                ),
                priority=request.priority,
                created_at=request.created_at,
            )
            for request in requests
        ]

    async def _recent_admin_activity(self, window_start: datetime) -> list[AdminOverviewActivity]:
        stmt = (
            select(VerificationRequestEvent)
            .options(joinedload(VerificationRequestEvent.verification_request))
            .where(
                VerificationRequestEvent.event_source == VerificationRequestEventSource.ADMIN,
                VerificationRequestEvent.created_at >= window_start,
            )
            .order_by(VerificationRequestEvent.created_at.desc())
            .limit(_RECENT_ACTIVITY_LIMIT)
        )
        events = list((await self._session.execute(stmt)).scalars().unique().all())
        return [
            AdminOverviewActivity(
                public_id=event.public_id,
                verification_request_public_id=event.verification_request.public_id,
                event_type=event.event_type,
                # PostgreSQL enum columns may be materialized as strings by an async
                # driver, while tests and other paths retain the StrEnum instance.
                event_source=(
                    event.event_source.value
                    if hasattr(event.event_source, "value")
                    else str(event.event_source)
                ),
                actor_user_id=event.actor_user_id,
                created_at=event.created_at,
            )
            for event in events
        ]

    async def _count(self, model, criterion=None) -> int:  # noqa: ANN001
        stmt = select(func.count()).select_from(model)
        if criterion is not None:
            stmt = stmt.where(criterion)
        return int((await self._session.execute(stmt)).scalar_one())
