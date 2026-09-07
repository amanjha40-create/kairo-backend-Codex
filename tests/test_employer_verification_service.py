"""Employer verifier workspace service regressions."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.employment.enums import EmployerVerificationDecision
from app.services.employer_verification_service import EmployerVerificationService
from app.verification_requests.enums import VerificationRequestStatus


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


def _service_for_portal_response(*, response: str = "pending"):
    employment = SimpleNamespace(id=uuid4(), verification_status="submitted", start_date=None)
    outreach = SimpleNamespace(
        public_id=uuid4(),
        employment=employment,
        verification_request_id=uuid4(),
        response=response,
        responded_at=None,
        remarks=None,
        response_metadata={},
        revoked_at=None,
        expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
    )
    request = SimpleNamespace(
        status=VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE,
        organization=SimpleNamespace(name="Acme Corp"),
    )
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    service = EmployerVerificationService.__new__(EmployerVerificationService)
    service._session = session
    service._load_portal_token_for_update = AsyncMock(return_value=outreach)
    service._verification_requests = SimpleNamespace(get_by_id=AsyncMock(return_value=request))
    service._notify_admin_quality_review_needed = AsyncMock()
    service._emit_audit = AsyncMock()

    async def transition(row, *, target_status, **_kwargs):
        row.status = target_status

    service._workflow = SimpleNamespace(transition=AsyncMock(side_effect=transition))
    return service, session, outreach, request


@pytest.mark.asyncio
async def test_portal_reject_persists_reason_and_transitions_once_with_nullable_start_date() -> None:
    service, session, outreach, request = _service_for_portal_response()

    response = await service.reject_from_portal(
        "token-value-long-enough",
        SimpleNamespace(reason="Dates do not match", comments="Please correct the dates"),
    )

    assert response.decision is EmployerVerificationDecision.DECLINED
    assert response.verification_request_status == "pending_admin_quality_review"
    assert outreach.response == EmployerVerificationDecision.DECLINED.value
    assert outreach.remarks == "Please correct the dates"
    assert outreach.response_metadata == {"reason": "Dates do not match"}
    assert request.status is VerificationRequestStatus.PENDING_ADMIN_QUALITY_REVIEW
    assert service._workflow.transition.await_count == 2
    service._emit_audit.assert_awaited_once()
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_portal_verify_transitions_to_admin_quality_review() -> None:
    service, session, outreach, request = _service_for_portal_response()

    response = await service.verify_from_portal(
        "token-value-long-enough",
        SimpleNamespace(employment_existed=True, dates_correct=True, role_correct=True, comments=None),
    )

    assert response.decision is EmployerVerificationDecision.CONFIRMED
    assert response.verification_request_status == "pending_admin_quality_review"
    assert outreach.response == EmployerVerificationDecision.CONFIRMED.value
    assert request.status is VerificationRequestStatus.PENDING_ADMIN_QUALITY_REVIEW
    service._emit_audit.assert_awaited_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_portal_clarify_transitions_to_awaiting_information() -> None:
    service, session, outreach, request = _service_for_portal_response()

    response = await service.request_clarification_from_portal(
        "token-value-long-enough",
        SimpleNamespace(reason="Please provide dates", comments="Start date is missing"),
    )

    assert response.decision is EmployerVerificationDecision.ON_HOLD
    assert response.verification_request_status == "awaiting_information"
    assert outreach.response == EmployerVerificationDecision.ON_HOLD.value
    assert request.status is VerificationRequestStatus.AWAITING_INFORMATION
    service._emit_audit.assert_awaited_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_portal_reject_replay_is_idempotent_without_duplicate_audit() -> None:
    service, session, outreach, request = _service_for_portal_response(response="declined")
    request.status = VerificationRequestStatus.PENDING_ADMIN_QUALITY_REVIEW

    response = await service.reject_from_portal(
        "token-value-long-enough",
        SimpleNamespace(reason="Dates do not match", comments=None),
    )

    assert response.idempotent is True
    service._workflow.transition.assert_not_awaited()
    service._emit_audit.assert_not_awaited()
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_portal_reject_rolls_back_all_pending_writes_on_precommit_failure() -> None:
    service, session, _outreach, _request = _service_for_portal_response()
    service._notify_admin_quality_review_needed = AsyncMock(side_effect=RuntimeError("notification failure"))

    with pytest.raises(RuntimeError, match="notification failure"):
        await service.reject_from_portal(
            "token-value-long-enough",
            SimpleNamespace(reason="Dates do not match", comments=None),
        )

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()
