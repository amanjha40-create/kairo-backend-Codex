"""Workflow engine for verification request status transitions."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.exceptions import ConflictError
from app.models.verification_request import VerificationRequest
from app.models.verification_request_event import VerificationRequestEvent
from app.repositories.verification_request import VerificationRequestRepository
from app.verification_requests.enums import (
    VerificationRequestEventSource,
    VerificationRequestStatus,
)


class VerificationRequestWorkflowService:
    """Owns all valid transitions and immutable event generation."""

    VALID_TRANSITIONS: dict[VerificationRequestStatus, set[VerificationRequestStatus]] = {
        VerificationRequestStatus.DRAFT: {
            VerificationRequestStatus.PENDING_SUBJECT_ACCEPTANCE,
            VerificationRequestStatus.CANCELLED,
        },
        VerificationRequestStatus.PENDING_SUBJECT_ACCEPTANCE: {
            VerificationRequestStatus.ACCEPTED,
            VerificationRequestStatus.REJECTED,
            VerificationRequestStatus.CANCELLED,
            VerificationRequestStatus.EXPIRED,
        },
        VerificationRequestStatus.ACCEPTED: {
            VerificationRequestStatus.IN_PROGRESS,
            VerificationRequestStatus.CANCELLED,
        },
        VerificationRequestStatus.IN_PROGRESS: {
            VerificationRequestStatus.AWAITING_INFORMATION,
            VerificationRequestStatus.VERIFIED,
            VerificationRequestStatus.REJECTED,
            VerificationRequestStatus.CANCELLED,
        },
        VerificationRequestStatus.AWAITING_INFORMATION: {
            VerificationRequestStatus.IN_PROGRESS,
            VerificationRequestStatus.REJECTED,
            VerificationRequestStatus.CANCELLED,
        },
        VerificationRequestStatus.VERIFIED: set(),
        VerificationRequestStatus.REJECTED: set(),
        VerificationRequestStatus.CANCELLED: set(),
        VerificationRequestStatus.EXPIRED: set(),
    }

    def __init__(self, repo: VerificationRequestRepository) -> None:
        self._repo = repo

    async def record_creation(
        self,
        request: VerificationRequest,
        *,
        actor_user_id: UUID | None,
        event_source: VerificationRequestEventSource,
        metadata: dict[str, Any] | None = None,
    ) -> VerificationRequestEvent:
        return await self._repo.append_event(
            VerificationRequestEvent(
                verification_request_id=request.id,
                actor_user_id=actor_user_id,
                event_type="verification_request_created",
                event_source=event_source,
                previous_status=None,
                new_status=request.status,
                metadata_payload=metadata or {},
            )
        )

    async def transition(
        self,
        request: VerificationRequest,
        *,
        target_status: VerificationRequestStatus,
        actor_user_id: UUID | None,
        event_type: str,
        event_source: VerificationRequestEventSource,
        metadata: dict[str, Any] | None = None,
    ) -> VerificationRequestEvent:
        current_status = request.status
        self._assert_valid_transition(current_status, target_status)
        request.status = target_status
        return await self._repo.append_event(
            VerificationRequestEvent(
                verification_request_id=request.id,
                actor_user_id=actor_user_id,
                event_type=event_type,
                event_source=event_source,
                previous_status=current_status,
                new_status=target_status,
                metadata_payload=metadata or {},
            )
        )

    def _assert_valid_transition(
        self,
        current_status: VerificationRequestStatus,
        target_status: VerificationRequestStatus,
    ) -> None:
        if current_status == target_status:
            raise ConflictError("Verification request is already in the requested status")
        allowed = self.VALID_TRANSITIONS.get(current_status, set())
        if target_status not in allowed:
            raise ConflictError(
                f"Verification request cannot transition from {current_status.value} to {target_status.value}"
            )
