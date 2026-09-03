"""Focused safety tests for the admin-controlled verification lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.education.enums import EducationVerificationStatus
from app.employment.enums import VerificationStatus
from app.exceptions import ConflictError, NotFoundError
from app.schemas.admin_review_workflow import (
    AdminReviewDecisionRequest,
    AdminReviewDirectConfirmationRequest,
)
from app.schemas.pagination import ListQueryParams
from app.services.verification_request_admin_review_service import (
    VerificationRequestAdminReviewService,
)
from app.services.verification_request_service import VerificationRequestService
from app.services.verification_request_workflow_service import (
    VerificationRequestWorkflowService,
)
from app.verification_requests.enums import (
    VerificationRequestEventSource,
    VerificationRequestStatus,
    VerificationRequestType,
)


class FakeVerificationRequestRepository:
    def __init__(self) -> None:
        self.events = []

    async def append_event(self, event):  # noqa: ANN001
        self.events.append(event)
        return event


def _request(status: VerificationRequestStatus) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        status=status,
        employment_id=uuid4(),
        education_id=None,
        request_type=VerificationRequestType.EMPLOYMENT,
        subject_user_id=uuid4(),
        consented_at=datetime.now(tz=UTC),
        consented_fields=["employment.role"],
        consented_evidence_scope=["employment_letter"],
    )


@pytest.mark.asyncio
async def test_verifier_cannot_transition_directly_to_terminal_status() -> None:
    workflow = VerificationRequestWorkflowService(FakeVerificationRequestRepository())  # type: ignore[arg-type]
    request = _request(VerificationRequestStatus.IN_PROGRESS)

    for terminal_status in {
        VerificationRequestStatus.VERIFIED,
        VerificationRequestStatus.REJECTED,
    }:
        with pytest.raises(ConflictError):
            await workflow.transition(
                request,
                target_status=terminal_status,
                actor_user_id=uuid4(),
                event_type="verification_response_received",
                event_source=VerificationRequestEventSource.ORGANIZATION,
            )

    await workflow.transition(
        request,
        target_status=VerificationRequestStatus.PENDING_ADMIN_QUALITY_REVIEW,
        actor_user_id=uuid4(),
        event_type="verification_response_received",
        event_source=VerificationRequestEventSource.ORGANIZATION,
    )
    assert request.status == VerificationRequestStatus.PENDING_ADMIN_QUALITY_REVIEW


def test_organization_cannot_view_request_before_admin_dispatch() -> None:
    request = _request(VerificationRequestStatus.PENDING_ADMIN_REVIEW)

    with pytest.raises(NotFoundError):
        VerificationRequestService._require_organization_visibility(request)

    request.status = VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE
    VerificationRequestService._require_organization_visibility(request)


@pytest.mark.asyncio
async def test_admin_finalization_updates_linked_employment_only() -> None:
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    subject_user_id = uuid4()
    employment = SimpleNamespace(
        created_by_user_id=subject_user_id,
        verification_status=VerificationStatus.SUBMITTED.value,
        reviewed_at=None,
        verified_at=None,
        reviewed_by_user_id=None,
        reviewer_summary=None,
    )
    service._employments = SimpleNamespace(get_active_by_id=AsyncMock(return_value=employment))
    request = SimpleNamespace(
        employment_id=uuid4(),
        education_id=None,
        subject_user_id=subject_user_id,
    )

    await service._apply_canonical_outcome(request, uuid4(), "verified", "Confirmed by verifier")

    assert employment.verification_status == VerificationStatus.VERIFIED.value
    assert employment.verified_at is not None
    assert employment.reviewer_summary == "Confirmed by verifier"
    assert employment.reviewed_by_user_id is not None


def _direct_confirmation_payload(
    *,
    method: str = "phone",
    outcome: str = "details_confirmed",
) -> AdminReviewDirectConfirmationRequest:
    return AdminReviewDirectConfirmationRequest(
        confirmation_method=method,
        confirmed_by="Pat Verifier",
        verifier_role="HR Manager",
        contact_detail_used=("pat.verifier@example.com" if method == "email" else "+91 98XXXXXX10"),
        confirmation_outcome=outcome,
        internal_note="Confirmed employer, title, and dates directly.",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        VerificationRequestStatus.PENDING_ADMIN_REVIEW,
        VerificationRequestStatus.PENDING_ADMIN_RE_REVIEW,
        VerificationRequestStatus.APPROVED_FOR_ORGANIZATION_VERIFICATION,
        VerificationRequestStatus.PENDING_ORGANIZATION_RESOLUTION,
        VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE,
        VerificationRequestStatus.IN_PROGRESS,
        VerificationRequestStatus.PENDING_ADMIN_QUALITY_REVIEW,
    ],
)
async def test_admin_direct_confirmation_supports_selected_operational_states(status) -> None:  # noqa: ANN001
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    request = _request(status)
    request.public_id = uuid4()
    refreshed = _request(VerificationRequestStatus.VERIFIED)
    refreshed.public_id = request.public_id
    review = SimpleNamespace(
        review_status=None,
        decision_by_user_id=None,
        decision_at=None,
        decision_summary=None,
    )
    service._get_required_request_for_update = AsyncMock(return_value=request)
    service._require_linked_canonical_claim = AsyncMock()
    service._get_or_create_review = AsyncMock(return_value=review)
    service._workflow = SimpleNamespace(
        transition_via_admin_direct_confirmation=AsyncMock(),
        record_action=AsyncMock(),
    )
    service._apply_canonical_outcome = AsyncMock()
    service._session = SimpleNamespace(commit=AsyncMock())
    service._notify_finalization = AsyncMock()
    service._requests = SimpleNamespace(get_by_public_id=AsyncMock(return_value=refreshed))
    expected_response = SimpleNamespace(status=VerificationRequestStatus.VERIFIED)
    service._to_request_response = AsyncMock(return_value=expected_response)
    actor_id = uuid4()

    result = await service.direct_confirm(
        actor_id,
        request.public_id,
        _direct_confirmation_payload(),
    )

    assert result is expected_response
    transition = service._workflow.transition_via_admin_direct_confirmation.await_args.kwargs
    assert transition["metadata"]["reason"] == "manual_direct_confirmation"
    assert transition["metadata"]["confirmation_method"] == "phone"
    assert transition["metadata"]["confirmed_by"] == "Pat Verifier"
    assert transition["metadata"]["verifier_role"] == "HR Manager"
    assert transition["metadata"]["contact_detail_used"] == "+91 98XXXXXX10"
    service._apply_canonical_outcome.assert_awaited_once_with(
        request,
        actor_id,
        "verified",
        "Confirmed employer, title, and dates directly.",
    )
    service._session.commit.assert_awaited_once()
    service._notify_finalization.assert_awaited_once_with(request, actor_id, "verified")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        VerificationRequestStatus.VERIFIED,
        VerificationRequestStatus.REJECTED,
        VerificationRequestStatus.UNABLE_TO_VERIFY,
        VerificationRequestStatus.CANCELLED,
        VerificationRequestStatus.EXPIRED,
        VerificationRequestStatus.AWAITING_SUBJECT_CORRECTIONS,
        VerificationRequestStatus.AWAITING_INFORMATION,
    ],
)
async def test_admin_direct_confirmation_fails_closed_outside_allowed_states(status) -> None:  # noqa: ANN001
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    request = _request(status)
    request.public_id = uuid4()
    service._get_required_request_for_update = AsyncMock(return_value=request)

    with pytest.raises(ConflictError, match="not eligible"):
        await service.direct_confirm(uuid4(), request.public_id, _direct_confirmation_payload())


@pytest.mark.asyncio
async def test_direct_confirmation_discrepancy_does_not_mark_request_verified() -> None:
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    request = _request(VerificationRequestStatus.PENDING_ADMIN_REVIEW)
    request.public_id = uuid4()
    service._get_required_request_for_update = AsyncMock(return_value=request)
    service._workflow = SimpleNamespace(transition_via_admin_direct_confirmation=AsyncMock())

    with pytest.raises(ConflictError, match="correction workflow"):
        await service.direct_confirm(
            uuid4(),
            request.public_id,
            _direct_confirmation_payload(outcome="details_confirmed_with_discrepancy"),
        )

    assert request.status == VerificationRequestStatus.PENDING_ADMIN_REVIEW
    service._workflow.transition_via_admin_direct_confirmation.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["phone", "email"])
async def test_direct_confirmation_event_persists_method_and_contact(method: str) -> None:
    repository = FakeVerificationRequestRepository()
    workflow = VerificationRequestWorkflowService(repository)  # type: ignore[arg-type]
    request = _request(VerificationRequestStatus.IN_PROGRESS)
    actor_id = uuid4()
    payload = _direct_confirmation_payload(method=method)
    metadata = {
        "reason": "manual_direct_confirmation",
        "confirmation_method": payload.confirmation_method,
        "confirmed_by": payload.confirmed_by,
        "verifier_role": payload.verifier_role,
        "contact_detail_used": payload.contact_detail_used,
        "internal_note": payload.internal_note,
    }

    event = await workflow.transition_via_admin_direct_confirmation(
        request,
        actor_user_id=actor_id,
        metadata=metadata,
    )

    assert request.status == VerificationRequestStatus.VERIFIED
    assert event.event_type == "verification_request_manual_direct_confirmation"
    assert event.previous_status == VerificationRequestStatus.IN_PROGRESS
    assert event.new_status == VerificationRequestStatus.VERIFIED
    assert event.actor_user_id == actor_id
    assert event.metadata_payload["confirmation_method"] == method
    assert event.metadata_payload["contact_detail_used"] == payload.contact_detail_used
    assert repository.events == [event]

    with pytest.raises(ConflictError, match="not eligible"):
        await workflow.transition_via_admin_direct_confirmation(
            request,
            actor_user_id=actor_id,
            metadata=metadata,
        )
    assert repository.events == [event]


@pytest.mark.asyncio
async def test_admin_timeline_resolves_canonical_actor_identity() -> None:
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    actor_id = uuid4()
    request = SimpleNamespace(id=uuid4(), public_id=uuid4())
    event = SimpleNamespace(
        public_id=uuid4(),
        actor_user_id=actor_id,
        event_type="verification_request_manual_direct_confirmation",
        event_source=VerificationRequestEventSource.ADMIN,
        previous_status=VerificationRequestStatus.IN_PROGRESS,
        new_status=VerificationRequestStatus.VERIFIED,
        metadata_payload={"confirmation_method": "phone"},
        created_at=datetime.now(tz=UTC),
    )
    actor = SimpleNamespace(full_name="Admin Operator", email="operator@example.com")
    service._get_required_request = AsyncMock(return_value=request)
    service._requests = SimpleNamespace(list_timeline=AsyncMock(return_value=[event]))
    service._users = SimpleNamespace(get_by_id=AsyncMock(return_value=actor))

    result = await service.get_timeline(
        request.public_id,
        ListQueryParams(page=1, page_size=100),
    )

    assert result.timeline.total == 1
    assert result.timeline.items[0].actor_display_name == "Admin Operator"
    assert result.timeline.items[0].actor_email == "operator@example.com"
    service._users.get_by_id.assert_awaited_once_with(actor_id)


@pytest.mark.asyncio
async def test_admin_finalization_updates_linked_education_only() -> None:
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    subject_user_id = uuid4()
    education = SimpleNamespace(
        user_id=subject_user_id,
        verification_status=EducationVerificationStatus.SUBMITTED.value,
        reviewed_at=None,
        verified_at=None,
        reviewed_by_user_id=None,
        reviewer_note=None,
    )
    service._educations = SimpleNamespace(get_active_by_id=AsyncMock(return_value=education))
    request = SimpleNamespace(
        employment_id=None,
        education_id=uuid4(),
        subject_user_id=subject_user_id,
    )

    await service._apply_canonical_outcome(request, uuid4(), "rejected", "Discrepancy confirmed")

    assert education.verification_status == EducationVerificationStatus.REJECTED.value
    assert education.verified_at is None
    assert education.reviewer_note == "Discrepancy confirmed"
    assert education.reviewed_by_user_id is not None


@pytest.mark.asyncio
async def test_admin_finalization_marks_linked_education_verified_with_timestamp() -> None:
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    subject_user_id = uuid4()
    education = SimpleNamespace(
        user_id=subject_user_id,
        verification_status=EducationVerificationStatus.SUBMITTED.value,
        reviewed_at=None,
        verified_at=None,
        reviewed_by_user_id=None,
        reviewer_note=None,
    )
    service._educations = SimpleNamespace(get_active_by_id=AsyncMock(return_value=education))
    request = SimpleNamespace(
        employment_id=None,
        education_id=uuid4(),
        subject_user_id=subject_user_id,
    )

    await service._apply_canonical_outcome(request, uuid4(), "verified", "Education verified")

    assert education.verification_status == EducationVerificationStatus.VERIFIED.value
    assert education.verified_at is not None


@pytest.mark.asyncio
async def test_admin_finalization_notifies_candidate_once_with_authoritative_payload() -> None:
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    service._notifications = SimpleNamespace(create_and_dispatch=AsyncMock())
    request = SimpleNamespace(
        public_id=uuid4(),
        subject_user_id=uuid4(),
        subject_email="candidate@example.com",
        subject_name="Candidate User",
        target_organization_name="Example Corp",
        organization=None,
        request_type=VerificationRequestType.EMPLOYMENT,
    )

    await service._notify_finalization(request, uuid4(), "verified")

    service._notifications.create_and_dispatch.assert_awaited_once()
    notification_request = service._notifications.create_and_dispatch.await_args.args[0]
    assert notification_request.recipient_user_id == request.subject_user_id
    assert notification_request.recipient_email == request.subject_email
    assert notification_request.dedupe_key.endswith(":candidate")
    assert notification_request.payload["subject_name"] == request.subject_name
    assert notification_request.payload["organization_name"] == request.target_organization_name
    assert notification_request.payload["request_type"] == "employment"
    assert notification_request.payload["completed_at_iso"]


@pytest.mark.asyncio
async def test_admin_finalization_notifies_candidate_for_education_string_request_type() -> None:
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    service._notifications = SimpleNamespace(create_and_dispatch=AsyncMock())
    education_id = uuid4()
    request = SimpleNamespace(
        public_id=uuid4(),
        subject_user_id=uuid4(),
        subject_email="candidate@example.com",
        subject_name="Candidate User",
        target_organization_name="Example University",
        organization=None,
        request_type="education",
        employment_id=None,
        education_id=education_id,
    )

    await service._notify_finalization(request, uuid4(), "verified")

    service._notifications.create_and_dispatch.assert_awaited_once()
    notification_request = service._notifications.create_and_dispatch.await_args.args[0]
    assert notification_request.payload["request_type"] == "education"
    assert notification_request.payload["linked_record_type"] == "education"
    assert notification_request.payload["linked_record_id"] == str(education_id)
    assert notification_request.metadata["verification_request_public_id"] == str(request.public_id)
    assert notification_request.metadata["linked_record_type"] == "education"
    assert notification_request.metadata["linked_record_id"] == str(education_id)


@pytest.mark.asyncio
async def test_unlinked_legacy_request_fails_closed_at_finalization() -> None:
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    request = SimpleNamespace(
        employment_id=None,
        education_id=None,
        request_type=VerificationRequestType.EMPLOYMENT,
    )

    with pytest.raises(ConflictError, match="Legacy unlinked"):
        await service._require_linked_canonical_claim(request)


@pytest.mark.asyncio
async def test_pre_dispatch_rejection_never_finalizes_the_career_claim() -> None:
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    request = _request(VerificationRequestStatus.PENDING_ADMIN_REVIEW)
    request.public_id = uuid4()
    service._get_required_request = AsyncMock(return_value=request)
    service._close_pre_dispatch_request = AsyncMock(return_value="closed")
    service._finalize_request = AsyncMock(return_value="finalized")

    result = await service.reject(
        uuid4(),
        request.public_id,
        AdminReviewDecisionRequest(decision_summary="Insufficient evidence for outreach."),
    )

    assert result == "closed"
    service._close_pre_dispatch_request.assert_awaited_once()
    service._finalize_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalization_rejects_a_pre_dispatch_request() -> None:
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    request = _request(VerificationRequestStatus.PENDING_ADMIN_REVIEW)
    request.public_id = uuid4()
    service._get_required_request = AsyncMock(return_value=request)

    with pytest.raises(ConflictError, match="final quality review"):
        await service._finalize_request(
            uuid4(),
            request.public_id,
            outcome="verified",
            decision_summary="Not yet verified by an organization.",
        )


def test_admin_dispatch_requires_authoritative_consent() -> None:
    request = SimpleNamespace(
        consented_at=None,
        consented_fields=[],
        consented_evidence_scope=[],
    )

    with pytest.raises(ConflictError, match="authoritative candidate consent"):
        VerificationRequestAdminReviewService._require_authoritative_consent(request)


@pytest.mark.asyncio
async def test_return_to_verifier_moves_case_back_to_in_progress() -> None:
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    request = _request(VerificationRequestStatus.PENDING_ADMIN_QUALITY_REVIEW)
    request.public_id = uuid4()
    refreshed_request = _request(VerificationRequestStatus.IN_PROGRESS)
    refreshed_request.public_id = request.public_id
    service._require_admin_quality_review_request = AsyncMock(return_value=request)
    service._workflow = SimpleNamespace(transition=AsyncMock())
    service._session = SimpleNamespace(commit=AsyncMock())
    service._requests = SimpleNamespace(get_by_public_id=AsyncMock(return_value=refreshed_request))
    expected_response = SimpleNamespace(status=VerificationRequestStatus.IN_PROGRESS)
    service._to_request_response = AsyncMock(return_value=expected_response)

    result = await service.return_to_verifier(
        uuid4(),
        request.public_id,
        AdminReviewDecisionRequest(decision_summary="Verifier must confirm the end date."),
    )

    assert result is expected_response
    service._workflow.transition.assert_awaited_once()
    transition_call = service._workflow.transition.await_args.kwargs
    assert transition_call["target_status"] == VerificationRequestStatus.IN_PROGRESS
    assert transition_call["metadata"] == {
        "decision_summary": "Verifier must confirm the end date."
    }
    service._session.commit.assert_awaited_once()
    service._requests.get_by_public_id.assert_awaited_once_with(request.public_id)
    service._to_request_response.assert_awaited_once_with(refreshed_request)


@pytest.mark.asyncio
async def test_cancel_reloads_request_after_commit() -> None:
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    request = _request(VerificationRequestStatus.IN_PROGRESS)
    request.public_id = uuid4()
    refreshed_request = _request(VerificationRequestStatus.CANCELLED)
    refreshed_request.public_id = request.public_id
    service._get_required_request = AsyncMock(return_value=request)
    service._workflow = SimpleNamespace(transition=AsyncMock())
    service._session = SimpleNamespace(commit=AsyncMock())
    service._requests = SimpleNamespace(get_by_public_id=AsyncMock(return_value=refreshed_request))
    expected_response = SimpleNamespace(status=VerificationRequestStatus.CANCELLED)
    service._to_request_response = AsyncMock(return_value=expected_response)

    result = await service.cancel(
        uuid4(),
        request.public_id,
        AdminReviewDecisionRequest(decision_summary="Subject withdrew consent."),
    )

    assert result is expected_response
    service._workflow.transition.assert_awaited_once()
    transition_call = service._workflow.transition.await_args.kwargs
    assert transition_call["target_status"] == VerificationRequestStatus.CANCELLED
    assert transition_call["metadata"] == {"decision_summary": "Subject withdrew consent."}
    service._session.commit.assert_awaited_once()
    service._requests.get_by_public_id.assert_awaited_once_with(request.public_id)
    service._to_request_response.assert_awaited_once_with(refreshed_request)


@pytest.mark.asyncio
async def test_cancel_rejects_closed_request() -> None:
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    request = _request(VerificationRequestStatus.VERIFIED)
    request.public_id = uuid4()
    service._get_required_request = AsyncMock(return_value=request)

    with pytest.raises(ConflictError, match="already closed"):
        await service.cancel(
            uuid4(),
            request.public_id,
            AdminReviewDecisionRequest(decision_summary="Cancel requested after completion."),
        )
