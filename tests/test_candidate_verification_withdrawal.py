"""Candidate-owned verification-request withdrawal contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.education.enums import EducationVerificationStatus
from app.employment.enums import VerificationStatus as EmploymentVerificationStatus
from app.exceptions import ConflictError, NotFoundError
from app.schemas.verification_request import (
    EmploymentVerificationDraftRequest,
    VerificationContactRequest,
)
from app.services.verification_request_service import VerificationRequestService
from app.services.verification_request_workflow_service import (
    VerificationRequestWorkflowService,
)
from app.verification_requests.enums import (
    VerificationContactType,
    VerificationRequestEventSource,
    VerificationRequestStatus,
    VerificationRequestType,
)


def _request(
    actor_id,
    *,
    status=VerificationRequestStatus.PENDING_ADMIN_REVIEW,
    request_type=VerificationRequestType.EMPLOYMENT,
    claim_snapshot=None,
):
    employment_id = uuid4() if request_type == VerificationRequestType.EMPLOYMENT else None
    education_id = uuid4() if request_type == VerificationRequestType.EDUCATION else None
    return SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        subject_user_id=actor_id,
        subject_email="candidate@example.com",
        status=status,
        request_type=request_type,
        employment_id=employment_id,
        education_id=education_id,
        approved_for_organization_verification_at=None,
        organization_outreach_sent_at=None,
        withdrawn_at=None,
        withdrawn_by_user_id=None,
        claim_snapshot=claim_snapshot or {},
        consented_fields=["employment.role"],
        consented_evidence_scope=["employment_letter"],
    )


def _withdrawal_service(request, *, employment=None, education=None):
    service = VerificationRequestService.__new__(VerificationRequestService)
    service._requests = SimpleNamespace(
        get_by_public_id_for_update=AsyncMock(return_value=request),
    )
    service._employments = SimpleNamespace(
        get_owned_active_for_update=AsyncMock(return_value=employment),
        get_active_by_id=AsyncMock(return_value=employment),
    )
    service._educations = SimpleNamespace(
        get_owned_for_update=AsyncMock(return_value=education),
        get_active_by_id=AsyncMock(return_value=education),
    )

    async def transition(target, *, target_status, **_kwargs):
        target.status = target_status

    service._workflow = SimpleNamespace(transition=AsyncMock(side_effect=transition))
    service._commit_reload_subject_response = AsyncMock(return_value=request)
    service._to_subject_response = AsyncMock(return_value=request)
    return service


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        VerificationRequestStatus.PENDING_ADMIN_REVIEW,
        VerificationRequestStatus.PENDING_ADMIN_RE_REVIEW,
    ],
)
async def test_owner_can_withdraw_safe_pending_request_and_release_employment(status) -> None:
    actor_id = uuid4()
    snapshot = {"request_type": "employment", "role": "Original role"}
    request = _request(actor_id, status=status, claim_snapshot=snapshot)
    employment = SimpleNamespace(verification_status=EmploymentVerificationStatus.SUBMITTED.value)
    service = _withdrawal_service(request, employment=employment)

    result = await service.withdraw_by_candidate(
        actor_id,
        "candidate@example.com",
        request.public_id,
    )

    assert result is request
    assert request.status == VerificationRequestStatus.WITHDRAWN_BY_CANDIDATE
    assert request.withdrawn_at is not None
    assert request.withdrawn_by_user_id == actor_id
    assert request.claim_snapshot == snapshot
    assert request.consented_fields == ["employment.role"]
    assert request.consented_evidence_scope == ["employment_letter"]
    assert employment.verification_status == EmploymentVerificationStatus.DRAFT.value
    service._workflow.transition.assert_awaited_once_with(
        request,
        target_status=VerificationRequestStatus.WITHDRAWN_BY_CANDIDATE,
        actor_user_id=actor_id,
        event_type="verification_request_withdrawn_by_candidate",
        event_source=VerificationRequestEventSource.CANDIDATE,
        metadata={"withdrawn_at": request.withdrawn_at.isoformat()},
    )


@pytest.mark.asyncio
async def test_withdrawal_releases_education_edit_lock() -> None:
    actor_id = uuid4()
    request = _request(
        actor_id,
        request_type=VerificationRequestType.EDUCATION,
        claim_snapshot={"request_type": "education", "degree": "BSc"},
    )
    education = SimpleNamespace(verification_status=EducationVerificationStatus.PENDING.value)
    service = _withdrawal_service(request, education=education)

    await service.withdraw_by_candidate(actor_id, "candidate@example.com", request.public_id)

    assert education.verification_status == EducationVerificationStatus.DRAFT.value


@pytest.mark.asyncio
async def test_other_candidate_cannot_withdraw_request() -> None:
    owner_id = uuid4()
    request = _request(owner_id, claim_snapshot={"request_type": "employment"})
    service = _withdrawal_service(request)

    with pytest.raises(NotFoundError, match="Verification request not found"):
        await service.withdraw_by_candidate(uuid4(), "other@example.com", request.public_id)

    service._workflow.transition.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        VerificationRequestStatus.IN_PROGRESS,
        VerificationRequestStatus.VERIFIED,
        VerificationRequestStatus.REJECTED,
        VerificationRequestStatus.CANCELLED,
        VerificationRequestStatus.EXPIRED,
    ],
)
async def test_terminal_or_advanced_request_cannot_be_withdrawn(status) -> None:
    actor_id = uuid4()
    request = _request(actor_id, status=status, claim_snapshot={"request_type": "employment"})
    service = _withdrawal_service(request)

    with pytest.raises(ConflictError, match="processing has already progressed"):
        await service.withdraw_by_candidate(actor_id, "candidate@example.com", request.public_id)

    service._workflow.transition.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "progress_field",
    ["approved_for_organization_verification_at", "organization_outreach_sent_at"],
)
async def test_withdrawal_fails_closed_when_processing_timestamp_exists(progress_field) -> None:
    actor_id = uuid4()
    request = _request(actor_id, claim_snapshot={"request_type": "employment"})
    setattr(request, progress_field, datetime.now(tz=UTC))
    service = _withdrawal_service(request)

    with pytest.raises(ConflictError, match="processing has already progressed"):
        await service.withdraw_by_candidate(actor_id, "candidate@example.com", request.public_id)


@pytest.mark.asyncio
async def test_repeat_withdrawal_is_idempotent_without_duplicate_timeline_event() -> None:
    actor_id = uuid4()
    request = _request(
        actor_id,
        status=VerificationRequestStatus.WITHDRAWN_BY_CANDIDATE,
        claim_snapshot={"request_type": "employment"},
    )
    service = _withdrawal_service(request)

    result = await service.withdraw_by_candidate(
        actor_id, "candidate@example.com", request.public_id
    )

    assert result is request
    service._workflow.transition.assert_not_awaited()
    service._commit_reload_subject_response.assert_not_awaited()
    service._to_subject_response.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_legacy_pending_request_snapshot_is_frozen_before_editing_is_reenabled() -> None:
    actor_id = uuid4()
    request = _request(actor_id)
    employment = SimpleNamespace(
        verification_status=EmploymentVerificationStatus.SUBMITTED.value,
        employer_legal_name="Original Employer",
        job_title="Original role",
        start_date=date(2020, 1, 1),
        end_date=None,
        employment_type="full_time",
        work_location_country="IN",
        work_location_region="MH",
    )
    service = _withdrawal_service(request, employment=employment)

    await service.withdraw_by_candidate(actor_id, "candidate@example.com", request.public_id)
    employment.job_title = "Edited role"
    claim = service._build_employment_claim_response(request, employment, False)

    assert request.claim_snapshot["role"] == "Original role"
    assert claim.role == "Original role"
    assert claim.end_date is None


@pytest.mark.asyncio
async def test_withdrawn_request_is_not_reused_when_candidate_starts_again() -> None:
    actor_id = uuid4()
    employment_id = uuid4()
    document_id = uuid4()
    withdrawn_request = _request(
        actor_id,
        status=VerificationRequestStatus.WITHDRAWN_BY_CANDIDATE,
        claim_snapshot={"request_type": "employment", "role": "Old role"},
    )
    withdrawn_request.employment_id = employment_id
    employment = SimpleNamespace(
        id=employment_id,
        subject_full_name="Candidate",
        subject_email="candidate@example.com",
        employer_legal_name="Current Employer",
    )
    document = SimpleNamespace(id=document_id, document_type="employment_letter")
    created_requests = []
    service = VerificationRequestService.__new__(VerificationRequestService)

    async def create_request(request):
        request.id = uuid4()
        request.public_id = uuid4()
        created_requests.append(request)
        return request

    service._employments = SimpleNamespace(
        get_owned_active_for_update=AsyncMock(return_value=employment),
    )
    service._requests = SimpleNamespace(
        get_active_for_employment=AsyncMock(return_value=None),
        create=AsyncMock(side_effect=create_request),
    )
    service._require_subject_user = AsyncMock(
        return_value=SimpleNamespace(email="candidate@example.com")
    )
    service._contacts = SimpleNamespace(
        create=AsyncMock(return_value=SimpleNamespace(public_id=uuid4()))
    )
    service._employment_documents = SimpleNamespace(
        get_active_for_employment=AsyncMock(return_value=document)
    )
    service._validate_employment_document_evidence = AsyncMock()
    service._evidence = SimpleNamespace(
        create=AsyncMock(return_value=SimpleNamespace(public_id=uuid4()))
    )
    service._workflow = SimpleNamespace(record_action=AsyncMock())
    service._people = SimpleNamespace(resolve_for_verification_request=AsyncMock())
    service._commit_reload_subject_response = AsyncMock(
        side_effect=lambda public_id: next(
            request for request in created_requests if request.public_id == public_id
        )
    )
    payload = EmploymentVerificationDraftRequest(
        verification_contact=VerificationContactRequest(
            contact_email="hr@example.com",
            contact_type=VerificationContactType.HR,
        ),
        employment_document_ids=[document_id],
    )

    new_request = await service.create_employment_verification_draft(
        actor_id,
        employment_id,
        payload,
    )

    assert len(created_requests) == 1
    assert new_request.public_id != withdrawn_request.public_id
    assert new_request.status == VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION
    assert not new_request.claim_snapshot
    assert withdrawn_request.status == VerificationRequestStatus.WITHDRAWN_BY_CANDIDATE
    service._requests.get_active_for_employment.assert_awaited_once_with(employment_id)


def test_withdrawal_workflow_and_migration_contracts() -> None:
    assert (
        VerificationRequestStatus.WITHDRAWN_BY_CANDIDATE
        in VerificationRequestWorkflowService.VALID_TRANSITIONS[
            VerificationRequestStatus.PENDING_ADMIN_REVIEW
        ]
    )
    assert (
        VerificationRequestStatus.WITHDRAWN_BY_CANDIDATE
        in VerificationRequestWorkflowService.VALID_TRANSITIONS[
            VerificationRequestStatus.PENDING_ADMIN_RE_REVIEW
        ]
    )
    assert not VerificationRequestWorkflowService.VALID_TRANSITIONS[
        VerificationRequestStatus.WITHDRAWN_BY_CANDIDATE
    ]

    migration = Path("alembic/versions/075_candidate_verification_withdrawal.py").read_text()
    assert 'revision = "075"' in migration
    assert 'down_revision = "074"' in migration
    assert "withdrawn_by_candidate" in migration
    assert "claim_snapshot" in migration
