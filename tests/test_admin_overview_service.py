"""Service-level regression coverage for mixed enum/string admin projections."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.admin_overview_service import AdminOverviewService
from app.verification_requests.enums import (
    VerificationRequestEventSource,
    VerificationRequestStatus,
)


class _ScalarResult:
    def __init__(self, events):  # noqa: ANN001
        self._events = events

    def scalars(self):  # noqa: ANN201
        return self

    def unique(self):  # noqa: ANN201
        return self

    def all(self):  # noqa: ANN201
        return self._events


class _Session:
    def __init__(self, events):  # noqa: ANN001
        self._events = events

    async def execute(self, _statement):  # noqa: ANN001, ANN201
        return _ScalarResult(self._events)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_source", "expected_source"),
    [("admin", "admin"), (VerificationRequestEventSource.SYSTEM, "system")],
)
async def test_recent_admin_activity_accepts_string_backed_enum_values(
    event_source: str | VerificationRequestEventSource,
    expected_source: str,
) -> None:
    event = SimpleNamespace(
        public_id=uuid4(),
        verification_request=SimpleNamespace(public_id=uuid4()),
        event_type="verification_request_organization_resolved",
        event_source=event_source,
        actor_user_id=uuid4(),
        created_at=datetime.now(UTC),
    )
    service = AdminOverviewService(_Session([event]))  # type: ignore[arg-type]

    activity = await service._recent_admin_activity(datetime.now(UTC))

    assert activity[0].event_source == expected_source


@pytest.mark.asyncio
async def test_recent_cases_supports_admin_review_states_with_linked_claims() -> None:
    now = datetime.now(UTC)
    employment_request = SimpleNamespace(
        public_id=uuid4(),
        subject_name="Candidate Employment",
        organization=SimpleNamespace(name="Employer"),
        status=VerificationRequestStatus.PENDING_ADMIN_REVIEW,
        priority="normal",
        created_at=now,
        employment_id=uuid4(),
        education_id=None,
    )
    education_request = SimpleNamespace(
        public_id=uuid4(),
        subject_name="Candidate Education",
        organization=SimpleNamespace(name="Institution"),
        status="pending_admin_quality_review",
        priority="high",
        created_at=now,
        employment_id=None,
        education_id=uuid4(),
    )
    service = AdminOverviewService(_Session([employment_request, education_request]))  # type: ignore[arg-type]

    cases = await service._recent_cases(now)

    assert [case.status for case in cases] == [
        "pending_admin_review",
        "pending_admin_quality_review",
    ]
