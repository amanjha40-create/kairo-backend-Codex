"""Central verification status transition rules — admin, applicant, and system roles."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from app.employment.enums import VerificationStatus
from app.exceptions import ValidationAppError

Role = Literal["admin", "applicant", "system"]

# Reviewer console.
_ADMIN_VALID_TARGETS: Mapping[str, frozenset[str]] = {
    VerificationStatus.SUBMITTED.value: frozenset({VerificationStatus.UNDER_REVIEW.value}),
    VerificationStatus.UNDER_REVIEW.value: frozenset(
        {
            VerificationStatus.APPROVED.value,
            VerificationStatus.REJECTED.value,
            VerificationStatus.ADDITIONAL_INFO_REQUESTED.value,
        },
    ),
}

# Applicant — aligned with `EmploymentService` submit / cancel.
_APPLICANT_VALID_TARGETS: Mapping[str, frozenset[str]] = {
    VerificationStatus.DRAFT.value: frozenset(
        {
            VerificationStatus.SUBMITTED.value,
            VerificationStatus.CANCELLED.value,
        },
    ),
    VerificationStatus.ADDITIONAL_INFO_REQUESTED.value: frozenset({VerificationStatus.SUBMITTED.value}),
    VerificationStatus.SUBMITTED.value: frozenset({VerificationStatus.CANCELLED.value}),
}


class VerificationStatusManager:
    """Explicit transition graph for audit-friendly state changes."""

    @staticmethod
    def allowed_targets(current_status: str, *, role: Role) -> frozenset[str]:
        if role == "admin":
            return _ADMIN_VALID_TARGETS.get(current_status, frozenset())
        if role == "applicant":
            return _APPLICANT_VALID_TARGETS.get(current_status, frozenset())
        return frozenset()

    @staticmethod
    def require_transition(
        current_status: str,
        target_status: str,
        *,
        role: Role,
    ) -> None:
        """Raise ValidationAppError when the edge is not permitted."""

        allowed = VerificationStatusManager.allowed_targets(current_status, role=role)
        if target_status not in allowed:
            raise ValidationAppError(
                f"Illegal verification transition from {current_status!r} to {target_status!r} for role={role}",
                code="verification_transition_invalid",
            )

    @staticmethod
    def require_admin_transition(current_status: str, target_status: str) -> None:
        """Reviewer-only transitions (HTTP admin routes)."""

        VerificationStatusManager.require_transition(
            current_status,
            target_status,
            role="admin",
        )
