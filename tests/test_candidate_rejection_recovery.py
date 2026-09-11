"""Candidate recovery contracts after a terminal verification rejection."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.education.enums import EducationVerificationStatus
from app.employment.enums import VerificationStatus
from app.exceptions import NotFoundError
from app.schemas.education import EducationUpdateRequest
from app.schemas.employment import EmploymentUpdate
from app.schemas.verification_request import (
    EmploymentVerificationDraftRequest,
    VerificationContactRequest,
)
from app.services.education_service import EducationService
from app.services.employment_service import EmploymentService
from app.services.verification_request_admin_review_service import (
    VerificationRequestAdminReviewService,
)
from app.services.verification_request_service import VerificationRequestService
from app.verification_requests.enums import (
    VerificationContactType,
    VerificationRequestStatus,
)


@pytest.mark.asyncio
async def test_pre_dispatch_rejection_updates_linked_career_outcome() -> None:
    service = VerificationRequestAdminReviewService.__new__(
        VerificationRequestAdminReviewService
    )
    actor_id = uuid4()
    request = SimpleNamespace(
        public_id=uuid4(),
        employment_id=uuid4(),
        education_id=None,
        status=VerificationRequestStatus.PENDING_ADMIN_REVIEW,
    )
    review = SimpleNamespace(
        review_status=None,
        decision_by_user_id=None,
        decision_at=None,
        decision_summary=None,
    )
    service._get_or_create_review = AsyncMock(return_value=review)

    async def transition(target, *, target_status, **_kwargs):
        target.status = target_status

    service._workflow = SimpleNamespace(transition=AsyncMock(side_effect=transition))
    service._apply_canonical_outcome = AsyncMock()
    service._session = SimpleNamespace(commit=AsyncMock())
    service._requests = SimpleNamespace(get_by_public_id=AsyncMock(return_value=request))
    service._to_request_response = AsyncMock(return_value=request)

    result = await service._close_pre_dispatch_request(
        request,
        actor_id,
        target_status=VerificationRequestStatus.REJECTED,
        decision_summary="Employment dates need correction",
    )

    assert result is request
    assert request.status == VerificationRequestStatus.REJECTED
    service._apply_canonical_outcome.assert_awaited_once_with(
        request,
        actor_id,
        "rejected",
        "Employment dates need correction",
    )


@pytest.mark.asyncio
async def test_rejected_employment_edit_resets_current_record_only(monkeypatch) -> None:
    actor_id = uuid4()
    row = SimpleNamespace(
        id=uuid4(),
        verification_status=VerificationStatus.REJECTED.value,
        job_title="Old title",
        start_date=date(2020, 1, 1),
        end_date=None,
        submitted_at=datetime.now(tz=UTC),
        reviewed_at=datetime.now(tz=UTC),
        verified_at=None,
        reviewed_by_user_id=uuid4(),
        reviewer_summary="Title did not match",
        pending_info_request=None,
    )
    historical_snapshot = {"role": "Old title"}
    service = EmploymentService.__new__(EmploymentService)
    service._employment = SimpleNamespace(get_owned_active=AsyncMock(return_value=row))
    service._emit_audit = AsyncMock()
    service._verification_requests = SimpleNamespace(
        get_active_for_employment=AsyncMock(return_value=None)
    )
    service._verification_workflow = SimpleNamespace(record_action=AsyncMock())
    service._session = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    monkeypatch.setattr(
        "app.services.employment_service.EmploymentPublic.model_validate",
        lambda value: value,
    )

    result = await service.update(
        actor_id,
        row.id,
        EmploymentUpdate(job_title="Corrected title"),
    )

    assert result is row
    assert row.job_title == "Corrected title"
    assert row.verification_status == VerificationStatus.DRAFT.value
    assert row.submitted_at is None
    assert row.reviewed_at is None
    assert row.reviewed_by_user_id is None
    assert row.reviewer_summary is None
    assert historical_snapshot == {"role": "Old title"}
    service._emit_audit.assert_awaited_once()
    assert service._emit_audit.await_args.kwargs["previous_status"] == "rejected"
    assert service._emit_audit.await_args.kwargs["new_status"] == "draft"


@pytest.mark.asyncio
async def test_legacy_rejected_employment_edit_is_detected_from_request(
    monkeypatch,
) -> None:
    actor_id = uuid4()
    row = SimpleNamespace(
        id=uuid4(),
        verification_status=VerificationStatus.DRAFT.value,
        job_title="Old title",
        start_date=date(2020, 1, 1),
        end_date=None,
        submitted_at=datetime.now(tz=UTC),
        reviewed_at=datetime.now(tz=UTC),
        verified_at=None,
        reviewed_by_user_id=uuid4(),
        reviewer_summary="Title did not match",
        pending_info_request=None,
    )
    service = EmploymentService.__new__(EmploymentService)
    service._employment = SimpleNamespace(get_owned_active=AsyncMock(return_value=row))
    service._emit_audit = AsyncMock()
    service._verification_requests = SimpleNamespace(
        get_latest_for_subject_employment=AsyncMock(
            return_value=SimpleNamespace(status=VerificationRequestStatus.REJECTED)
        ),
        get_active_for_employment=AsyncMock(return_value=None),
    )
    service._verification_workflow = SimpleNamespace(record_action=AsyncMock())
    service._session = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    monkeypatch.setattr(
        "app.services.employment_service.EmploymentPublic.model_validate",
        lambda value: value,
    )

    await service.update(
        actor_id,
        row.id,
        EmploymentUpdate(job_title="Corrected title"),
    )

    assert row.verification_status == VerificationStatus.DRAFT.value
    assert row.submitted_at is None
    assert row.reviewed_at is None
    assert row.reviewed_by_user_id is None
    assert row.reviewer_summary is None


@pytest.mark.asyncio
async def test_rejected_education_edit_resets_current_record_only() -> None:
    actor_id = uuid4()
    education = SimpleNamespace(
        id=uuid4(),
        verification_status=EducationVerificationStatus.REJECTED.value,
        institution_name="Old University",
        degree="BSc",
        field_of_study="Science",
        start_date=date(2018, 1, 1),
        end_date=date(2021, 1, 1),
        is_currently_studying=False,
        submitted_at=datetime.now(tz=UTC),
        reviewed_at=datetime.now(tz=UTC),
        verified_at=None,
        reviewed_by_user_id=uuid4(),
        reviewer_note="Institution name needs correction",
    )
    service = EducationService.__new__(EducationService)
    service.get_owned = AsyncMock(return_value=education)
    service._assert_not_obvious_duplicate = AsyncMock()
    service._session = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())

    result = await service.update(
        actor_id,
        education.id,
        EducationUpdateRequest(institution_name="Corrected University"),
    )

    assert result is education
    assert education.institution_name == "Corrected University"
    assert education.verification_status == EducationVerificationStatus.DRAFT.value
    assert education.submitted_at is None
    assert education.reviewed_at is None
    assert education.reviewed_by_user_id is None
    assert education.reviewer_note is None


@pytest.mark.asyncio
async def test_legacy_rejected_education_edit_is_detected_from_request() -> None:
    actor_id = uuid4()
    education = SimpleNamespace(
        id=uuid4(),
        verification_status=EducationVerificationStatus.PENDING.value,
        institution_name="Old University",
        degree="BSc",
        field_of_study="Science",
        start_date=date(2018, 1, 1),
        end_date=date(2021, 1, 1),
        is_currently_studying=False,
        submitted_at=datetime.now(tz=UTC),
        reviewed_at=datetime.now(tz=UTC),
        verified_at=None,
        reviewed_by_user_id=uuid4(),
        reviewer_note="Institution name needs correction",
    )
    service = EducationService.__new__(EducationService)
    service.get_owned = AsyncMock(return_value=education)
    service._assert_not_obvious_duplicate = AsyncMock()
    service._verification_requests = SimpleNamespace(
        get_latest_for_subject_education=AsyncMock(
            return_value=SimpleNamespace(status=VerificationRequestStatus.REJECTED)
        )
    )
    service._session = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())

    await service.update(
        actor_id,
        education.id,
        EducationUpdateRequest(institution_name="Corrected University"),
    )

    assert education.verification_status == EducationVerificationStatus.DRAFT.value
    assert education.submitted_at is None
    assert education.reviewed_at is None
    assert education.reviewed_by_user_id is None
    assert education.reviewer_note is None


@pytest.mark.asyncio
@pytest.mark.parametrize("request_type", ["employment", "education"])
async def test_recovered_draft_no_longer_exposes_rejected_request_as_current(
    request_type: str,
) -> None:
    service = VerificationRequestService.__new__(VerificationRequestService)
    actor_id = uuid4()
    record_id = uuid4()
    rejected_at = datetime.now(tz=UTC)
    request = SimpleNamespace(
        status=VerificationRequestStatus.REJECTED,
        updated_at=rejected_at,
    )
    record = SimpleNamespace(
        id=record_id,
        updated_at=rejected_at + timedelta(seconds=1),
        verification_status=(
            VerificationStatus.DRAFT.value
            if request_type == "employment"
            else EducationVerificationStatus.DRAFT.value
        ),
    )
    if request_type == "employment":
        service._employments = SimpleNamespace(
            get_owned_active=AsyncMock(return_value=record)
        )
        service._requests = SimpleNamespace(
            get_latest_for_subject_employment=AsyncMock(return_value=request)
        )
        call = service.get_employment_verification_request(actor_id, record_id)
    else:
        service._educations = SimpleNamespace(get_owned=AsyncMock(return_value=record))
        service._requests = SimpleNamespace(
            get_latest_for_subject_education=AsyncMock(return_value=request)
        )
        call = service.get_education_verification_request(actor_id, record_id)

    with pytest.raises(NotFoundError, match="verification request not found"):
        await call


@pytest.mark.asyncio
@pytest.mark.parametrize("request_type", ["employment", "education"])
async def test_unedited_legacy_draft_still_exposes_rejected_request(
    request_type: str,
) -> None:
    service = VerificationRequestService.__new__(VerificationRequestService)
    actor_id = uuid4()
    record_id = uuid4()
    rejected_at = datetime.now(tz=UTC)
    request = SimpleNamespace(
        status=VerificationRequestStatus.REJECTED,
        updated_at=rejected_at,
    )
    record = SimpleNamespace(
        id=record_id,
        updated_at=rejected_at - timedelta(seconds=1),
        verification_status=(
            VerificationStatus.DRAFT.value
            if request_type == "employment"
            else EducationVerificationStatus.DRAFT.value
        ),
    )
    service._to_subject_response = AsyncMock(return_value=request)
    if request_type == "employment":
        service._employments = SimpleNamespace(
            get_owned_active=AsyncMock(return_value=record)
        )
        service._requests = SimpleNamespace(
            get_latest_for_subject_employment=AsyncMock(return_value=request)
        )
        result = await service.get_employment_verification_request(actor_id, record_id)
    else:
        service._educations = SimpleNamespace(get_owned=AsyncMock(return_value=record))
        service._requests = SimpleNamespace(
            get_latest_for_subject_education=AsyncMock(return_value=request)
        )
        result = await service.get_education_verification_request(actor_id, record_id)

    assert result is request


@pytest.mark.asyncio
async def test_new_submission_after_rejection_creates_fresh_request() -> None:
    actor_id = uuid4()
    employment_id = uuid4()
    document_id = uuid4()
    rejected_request = SimpleNamespace(
        public_id=uuid4(),
        status=VerificationRequestStatus.REJECTED,
        claim_snapshot={"request_type": "employment", "role": "Old title"},
    )
    employment = SimpleNamespace(
        id=employment_id,
        subject_full_name="Candidate",
        subject_email="candidate@example.com",
        employer_legal_name="Example Employer",
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
        get_owned_active_for_update=AsyncMock(return_value=employment)
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

    assert new_request.public_id != rejected_request.public_id
    assert new_request.status == VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION
    assert rejected_request.status == VerificationRequestStatus.REJECTED
    assert rejected_request.claim_snapshot == {
        "request_type": "employment",
        "role": "Old title",
    }
    assert len(created_requests) == 1
