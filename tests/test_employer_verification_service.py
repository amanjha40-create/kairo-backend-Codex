"""Employer verifier workspace service regressions."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.employment.enums import EmployerVerificationDecision
from app.services.employer_verification_service import EmployerVerificationService


def _service_for_workspace(*, start_date: date | None, end_date: date | None) -> EmployerVerificationService:
    employment = SimpleNamespace(
        id=uuid4(),
        subject_full_name="Legacy Candidate",
        employer_trade_name=None,
        employer_legal_name="Acme Corp",
        job_title="Engineer",
        employment_type="full_time",
        start_date=start_date,
        end_date=end_date,
        work_location_country="IN",
        work_location_region="KA",
    )
    request = SimpleNamespace(
        public_id=uuid4(),
        employment=employment,
        verification_request_id=None,
        viewed_at=datetime.now(tz=UTC),
        response=EmployerVerificationDecision.PENDING.value,
        expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
        contact_name="HR Contact",
        relationship_to_subject="manager",
        verifier_email="hr@example.test",
    )
    service = EmployerVerificationService.__new__(EmployerVerificationService)
    service._load_portal_token = AsyncMock(return_value=request)
    service._docs = SimpleNamespace(list_all_active_for_employment=AsyncMock(return_value=[]))
    service._verification_requests = SimpleNamespace()
    return service


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("start_date", "end_date", "expected_start", "expected_end"),
    [
        (None, None, None, None),
        (date(2020, 1, 1), None, "2020-01-01", None),
        (date(2020, 1, 1), date(2024, 1, 1), "2020-01-01", "2024-01-01"),
    ],
)
async def test_public_verifier_workspace_serializes_nullable_employment_dates(
    start_date: date | None,
    end_date: date | None,
    expected_start: str | None,
    expected_end: str | None,
) -> None:
    service = _service_for_workspace(start_date=start_date, end_date=end_date)

    workspace = await service.get_portal_workspace("valid-token-value")

    assert workspace.employment.employer_name == "Acme Corp"
    assert workspace.employment.job_title == "Engineer"
    assert workspace.employment.start_date == expected_start
    assert workspace.employment.end_date == expected_end
