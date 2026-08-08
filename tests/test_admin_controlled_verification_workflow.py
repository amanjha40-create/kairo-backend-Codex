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
from app.schemas.admin_review_workflow import AdminReviewDecisionRequest
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

    assert employment.verification_status == VerificationStatus.APPROVED.value
    assert employment.reviewer_summary == "Confirmed by verifier"
    assert employment.reviewed_by_user_id is not None


@pytest.mark.asyncio
async def test_admin_finalization_updates_linked_education_only() -> None:
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    subject_user_id = uuid4()
    education = SimpleNamespace(
        user_id=subject_user_id,
        verification_status=EducationVerificationStatus.SUBMITTED.value,
        reviewed_at=None,
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
    assert education.reviewer_note == "Discrepancy confirmed"
    assert education.reviewed_by_user_id is not None


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
