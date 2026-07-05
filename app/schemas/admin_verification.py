"""Admin verification console — audit history projections."""

from __future__ import annotations

from datetime import datetime
from typing import TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.pagination import Page


class VerificationAuditEntryPublic(BaseModel):
    """Audit row for verification history — remarks use `metadata_payload.remark` when action is remark-added."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    employment_id: UUID
    actor_user_id: UUID | None
    action: str
    previous_status: str | None
    new_status: str | None
    metadata_payload: dict | None = None
    created_at: datetime


VerificationHistoryPage: TypeAlias = Page[VerificationAuditEntryPublic]
