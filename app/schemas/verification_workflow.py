"""API-facing DTOs for verification workflow (timeline, queues)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.employment.verification.timeline import TimelineEventKind, VerificationTimelineEvent


class VerificationTimelineEventPublic(BaseModel):
    """Timeline projection derived from audit events."""

    model_config = ConfigDict(use_enum_values=True)

    id: UUID
    employment_id: UUID
    actor_user_id: UUID | None
    created_at: datetime
    kind: TimelineEventKind
    audit_action: str = Field(description="Raw persisted audit code")
    previous_status: str | None
    new_status: str | None
    metadata: dict[str, Any] | None = None


def timeline_event_to_public(ev: VerificationTimelineEvent) -> VerificationTimelineEventPublic:
    return VerificationTimelineEventPublic(
        id=ev.id,
        employment_id=ev.employment_id,
        actor_user_id=ev.actor_user_id,
        created_at=ev.created_at,
        kind=ev.kind,
        audit_action=ev.audit_action,
        previous_status=ev.previous_status,
        new_status=ev.new_status,
        metadata=ev.metadata,
    )
