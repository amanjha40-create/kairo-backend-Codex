"""Human-readable verification timeline derived from immutable audit rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.employment.constants import TIMELINE_META_AI_PIPELINE_KIND
from app.employment.enums import VerificationAuditAction
from app.models.verification_audit import VerificationAuditEvent


class TimelineEventKind(StrEnum):
    """UI-facing bucket — derived from `VerificationAuditEvent.action`."""

    CASE_CREATED = "case_created"
    CASE_UPDATED = "case_updated"
    SUBMITTED = "submitted"
    CANCELLED = "cancelled"
    DOCUMENT_REGISTERED = "document_registered"
    DOCUMENT_UPLOAD_COMPLETED = "document_upload_completed"
    EXTRACTION_QUEUED = "extraction_queued"
    EXTRACTION_STARTED = "extraction_started"
    EXTRACTION_COMPLETED = "extraction_completed"
    EXTRACTION_FAILED = "extraction_failed"
    STATUS_CHANGED = "status_changed"
    REVIEW_ASSIGNED = "review_assigned"
    REMARK_ADDED = "remark_added"
    REVIEWER_NOTE = "reviewer_note"
    AI_PIPELINE_PREPARED = "ai_pipeline_prepared"
    UNKNOWN = "unknown"


_ACTION_TO_KIND: dict[str, TimelineEventKind] = {
    "employment_created": TimelineEventKind.CASE_CREATED,
    "employment_updated": TimelineEventKind.CASE_UPDATED,
    "employment_submitted": TimelineEventKind.SUBMITTED,
    "employment_cancelled": TimelineEventKind.CANCELLED,
    "document_registered": TimelineEventKind.DOCUMENT_REGISTERED,
    "document_upload_completed": TimelineEventKind.DOCUMENT_UPLOAD_COMPLETED,
    "extraction_queued": TimelineEventKind.EXTRACTION_QUEUED,
    "extraction_started": TimelineEventKind.EXTRACTION_STARTED,
    "extraction_completed": TimelineEventKind.EXTRACTION_COMPLETED,
    "extraction_failed": TimelineEventKind.EXTRACTION_FAILED,
    "verification_status_changed": TimelineEventKind.STATUS_CHANGED,
    "review_assigned": TimelineEventKind.REVIEW_ASSIGNED,
    "reviewer_remark_added": TimelineEventKind.REMARK_ADDED,
    "reviewer_note_recorded": TimelineEventKind.REVIEWER_NOTE,
}


@dataclass(frozen=True, slots=True)
class VerificationTimelineEvent:
    """Single timeline point — safe for JSON APIs (no ORM objects)."""

    id: UUID
    employment_id: UUID
    actor_user_id: UUID | None
    created_at: datetime
    kind: TimelineEventKind
    audit_action: str
    previous_status: str | None
    new_status: str | None
    metadata: dict[str, Any] | None


def from_audit_row(row: VerificationAuditEvent) -> VerificationTimelineEvent:
    meta = row.metadata_payload or {}
    kind = _ACTION_TO_KIND.get(row.action, TimelineEventKind.UNKNOWN)
    if (
        row.action == VerificationAuditAction.REVIEWER_NOTE_RECORDED.value
        and meta.get("kind") == TIMELINE_META_AI_PIPELINE_KIND
    ):
        kind = TimelineEventKind.AI_PIPELINE_PREPARED
    return VerificationTimelineEvent(
        id=row.id,
        employment_id=row.employment_id,
        actor_user_id=row.actor_user_id,
        created_at=row.created_at,
        kind=kind,
        audit_action=row.action,
        previous_status=row.previous_status,
        new_status=row.new_status,
        metadata=row.metadata_payload,
    )
