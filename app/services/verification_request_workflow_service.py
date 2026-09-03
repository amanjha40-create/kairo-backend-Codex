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

ADMIN_DIRECT_CONFIRMATION_STATUSES = frozenset(
    {
        VerificationRequestStatus.PENDING_ADMIN_REVIEW,
        VerificationRequestStatus.PENDING_ADMIN_RE_REVIEW,
        VerificationRequestStatus.APPROVED_FOR_ORGANIZATION_VERIFICATION,
        VerificationRequestStatus.PENDING_ORGANIZATION_RESOLUTION,
        VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE,
        VerificationRequestStatus.IN_PROGRESS,
        VerificationRequestStatus.PENDING_ADMIN_QUALITY_REVIEW,
    }
)


class VerificationRequestWorkflowService:
    """Owns all valid transitions and immutable event generation."""

    VALID_TRANSITIONS: dict[VerificationRequestStatus, set[VerificationRequestStatus]] = {
        VerificationRequestStatus.DRAFT: {
            VerificationRequestStatus.PENDING_SUBJECT_ACCEPTANCE,
            VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION,
            VerificationRequestStatus.CANCELLED,
        },
        VerificationRequestStatus.PENDING_SUBJECT_ACCEPTANCE: {
            VerificationRequestStatus.ACCEPTED,
            VerificationRequestStatus.REJECTED,
            VerificationRequestStatus.CANCELLED,
            VerificationRequestStatus.EXPIRED,
        },
        VerificationRequestStatus.ACCEPTED: {
            VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION,
            VerificationRequestStatus.PENDING_ADMIN_REVIEW,
            VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE,
            VerificationRequestStatus.IN_PROGRESS,
            VerificationRequestStatus.CANCELLED,
        },
        VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION: {
            VerificationRequestStatus.PENDING_ADMIN_REVIEW,
            VerificationRequestStatus.CANCELLED,
        },
        VerificationRequestStatus.PENDING_ADMIN_REVIEW: {
            VerificationRequestStatus.AWAITING_SUBJECT_CORRECTIONS,
            VerificationRequestStatus.APPROVED_FOR_ORGANIZATION_VERIFICATION,
            VerificationRequestStatus.REJECTED,
            VerificationRequestStatus.CANCELLED,
        },
        VerificationRequestStatus.AWAITING_SUBJECT_CORRECTIONS: {
            VerificationRequestStatus.PENDING_ADMIN_RE_REVIEW,
            VerificationRequestStatus.CANCELLED,
            VerificationRequestStatus.EXPIRED,
        },
        VerificationRequestStatus.PENDING_ADMIN_RE_REVIEW: {
            VerificationRequestStatus.AWAITING_SUBJECT_CORRECTIONS,
            VerificationRequestStatus.APPROVED_FOR_ORGANIZATION_VERIFICATION,
            VerificationRequestStatus.REJECTED,
            VerificationRequestStatus.CANCELLED,
        },
        VerificationRequestStatus.APPROVED_FOR_ORGANIZATION_VERIFICATION: {
            VerificationRequestStatus.PENDING_ORGANIZATION_RESOLUTION,
            VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE,
            VerificationRequestStatus.CANCELLED,
        },
        VerificationRequestStatus.PENDING_ORGANIZATION_RESOLUTION: {
            VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE,
            VerificationRequestStatus.REJECTED,
            VerificationRequestStatus.CANCELLED,
        },
        VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE: {
            VerificationRequestStatus.IN_PROGRESS,
            VerificationRequestStatus.REJECTED,
            VerificationRequestStatus.EXPIRED,
            VerificationRequestStatus.CANCELLED,
        },
        VerificationRequestStatus.IN_PROGRESS: {
            VerificationRequestStatus.AWAITING_INFORMATION,
            VerificationRequestStatus.PENDING_ADMIN_QUALITY_REVIEW,
            VerificationRequestStatus.CANCELLED,
        },
        VerificationRequestStatus.AWAITING_INFORMATION: {
            VerificationRequestStatus.IN_PROGRESS,
            VerificationRequestStatus.CANCELLED,
        },
        VerificationRequestStatus.PENDING_ADMIN_QUALITY_REVIEW: {
            VerificationRequestStatus.AWAITING_SUBJECT_CORRECTIONS,
            VerificationRequestStatus.IN_PROGRESS,
            VerificationRequestStatus.VERIFIED,
            VerificationRequestStatus.REJECTED,
            VerificationRequestStatus.UNABLE_TO_VERIFY,
            VerificationRequestStatus.CANCELLED,
        },
        VerificationRequestStatus.VERIFIED: set(),
        VerificationRequestStatus.REJECTED: set(),
        VerificationRequestStatus.UNABLE_TO_VERIFY: set(),
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

    async def record_action(
        self,
        request: VerificationRequest,
        *,
        actor_user_id: UUID | None,
        event_type: str,
        event_source: VerificationRequestEventSource,
        metadata: dict[str, Any] | None = None,
    ) -> VerificationRequestEvent:
        return await self._repo.append_event(
            VerificationRequestEvent(
                verification_request_id=request.id,
                actor_user_id=actor_user_id,
                event_type=event_type,
                event_source=event_source,
                previous_status=request.status,
                new_status=request.status,
                metadata_payload=metadata or {},
            )
        )

    async def transition_via_admin_direct_confirmation(
        self,
        request: VerificationRequest,
        *,
        actor_user_id: UUID,
        metadata: dict[str, Any],
    ) -> VerificationRequestEvent:
        """Apply the Admin-only override without widening normal transitions."""

        current_status = request.status
        if current_status not in ADMIN_DIRECT_CONFIRMATION_STATUSES:
            raise ConflictError("Verification request is not eligible for direct confirmation")
        request.status = VerificationRequestStatus.VERIFIED
        return await self._repo.append_event(
            VerificationRequestEvent(
                verification_request_id=request.id,
                actor_user_id=actor_user_id,
                event_type="verification_request_manual_direct_confirmation",
                event_source=VerificationRequestEventSource.ADMIN,
                previous_status=current_status,
                new_status=VerificationRequestStatus.VERIFIED,
                metadata_payload=metadata,
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
            message = (
                "Verification request cannot transition from "
                f"{current_status.value} to {target_status.value}"
            )
            raise ConflictError(message)
