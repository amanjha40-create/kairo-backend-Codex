"""Admin review domain enums."""

from __future__ import annotations

from enum import StrEnum


class VerificationRequestReviewStatus(StrEnum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_REVIEW = "in_review"
    CORRECTIONS_REQUESTED = "corrections_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class VerificationReviewNoteVisibility(StrEnum):
    INTERNAL = "internal"
    SUBJECT_VISIBLE = "subject_visible"
    ORGANIZATION_VISIBLE = "organization_visible"


class VerificationReviewNoteType(StrEnum):
    ASSIGNMENT = "assignment"
    REVIEW_NOTE = "review_note"
    CORRECTION_EXPLANATION = "correction_explanation"
    APPROVAL_SUMMARY = "approval_summary"
    REJECTION_SUMMARY = "rejection_summary"
    SYSTEM = "system"


class VerificationReviewCorrectionStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class VerificationRequestEvidenceStatus(StrEnum):
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NEEDS_CORRECTION = "needs_correction"
    SUPERSEDED = "superseded"
