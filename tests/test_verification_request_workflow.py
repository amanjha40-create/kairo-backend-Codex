"""Unit tests for verification request workflow transitions."""

from __future__ import annotations

import pytest

from app.exceptions import ConflictError
from app.models.verification_request import VerificationRequest
from app.services.verification_request_workflow_service import VerificationRequestWorkflowService
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


def _build_request(status: VerificationRequestStatus) -> VerificationRequest:
    return VerificationRequest(
        organization_id=None,  # type: ignore[arg-type]
        subject_name="Aman Jha",
        subject_email="aman3@test.com",
        request_type=VerificationRequestType.EMPLOYMENT,
        status=status,
        requested_by_user_id=None,  # type: ignore[arg-type]
        trust_context={},
    )


@pytest.mark.asyncio
async def test_record_creation_appends_initial_event() -> None:
    repo = FakeVerificationRequestRepository()
    workflow = VerificationRequestWorkflowService(repo)  # type: ignore[arg-type]
    request = _build_request(VerificationRequestStatus.PENDING_SUBJECT_ACCEPTANCE)

    event = await workflow.record_creation(
        request,
        actor_user_id=None,
        event_source=VerificationRequestEventSource.ORGANIZATION,
        metadata={"request_type": "employment"},
    )

    assert event.new_status == VerificationRequestStatus.PENDING_SUBJECT_ACCEPTANCE
    assert event.event_type == "verification_request_created"
    assert len(repo.events) == 1


@pytest.mark.asyncio
async def test_valid_transition_updates_status_and_records_event() -> None:
    repo = FakeVerificationRequestRepository()
    workflow = VerificationRequestWorkflowService(repo)  # type: ignore[arg-type]
    request = _build_request(VerificationRequestStatus.PENDING_SUBJECT_ACCEPTANCE)

    event = await workflow.transition(
        request,
        target_status=VerificationRequestStatus.ACCEPTED,
        actor_user_id=None,
        event_type="verification_request_subject_accepted",
        event_source=VerificationRequestEventSource.CANDIDATE,
        metadata={},
    )

    assert request.status == VerificationRequestStatus.ACCEPTED
    assert event.previous_status == VerificationRequestStatus.PENDING_SUBJECT_ACCEPTANCE
    assert event.new_status == VerificationRequestStatus.ACCEPTED
    assert len(repo.events) == 1


@pytest.mark.asyncio
async def test_invalid_transition_is_rejected() -> None:
    repo = FakeVerificationRequestRepository()
    workflow = VerificationRequestWorkflowService(repo)  # type: ignore[arg-type]
    request = _build_request(VerificationRequestStatus.PENDING_SUBJECT_ACCEPTANCE)

    with pytest.raises(ConflictError):
        await workflow.transition(
            request,
            target_status=VerificationRequestStatus.VERIFIED,
            actor_user_id=None,
            event_type="verification_request_verified",
            event_source=VerificationRequestEventSource.ORGANIZATION,
            metadata={},
        )


@pytest.mark.asyncio
async def test_admin_review_transition_is_allowed() -> None:
    repo = FakeVerificationRequestRepository()
    workflow = VerificationRequestWorkflowService(repo)  # type: ignore[arg-type]
    request = _build_request(VerificationRequestStatus.PENDING_ADMIN_REVIEW)

    event = await workflow.transition(
        request,
        target_status=VerificationRequestStatus.AWAITING_SUBJECT_CORRECTIONS,
        actor_user_id=None,
        event_type="verification_request_corrections_requested",
        event_source=VerificationRequestEventSource.ADMIN,
        metadata={"field_key": "employment.start_date"},
    )

    assert request.status == VerificationRequestStatus.AWAITING_SUBJECT_CORRECTIONS
    assert event.previous_status == VerificationRequestStatus.PENDING_ADMIN_REVIEW
    assert event.new_status == VerificationRequestStatus.AWAITING_SUBJECT_CORRECTIONS


@pytest.mark.asyncio
async def test_record_action_preserves_status() -> None:
    repo = FakeVerificationRequestRepository()
    workflow = VerificationRequestWorkflowService(repo)  # type: ignore[arg-type]
    request = _build_request(VerificationRequestStatus.PENDING_ADMIN_REVIEW)

    event = await workflow.record_action(
        request,
        actor_user_id=None,
        event_type="verification_request_review_assigned",
        event_source=VerificationRequestEventSource.ADMIN,
        metadata={"review_round": 1},
    )

    assert request.status == VerificationRequestStatus.PENDING_ADMIN_REVIEW
    assert event.previous_status == VerificationRequestStatus.PENDING_ADMIN_REVIEW
    assert event.new_status == VerificationRequestStatus.PENDING_ADMIN_REVIEW
