"""Admin overview response contracts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AdminOverviewCase(BaseModel):
    public_id: UUID
    subject_name: str
    organization_name: str | None
    status: str
    priority: str
    created_at: datetime


class AdminOverviewActivity(BaseModel):
    public_id: UUID
    verification_request_public_id: UUID
    event_type: str
    event_source: str
    actor_user_id: UUID | None
    created_at: datetime


class AdminOverviewResponse(BaseModel):
    generated_at: datetime
    recent_window_days: int = Field(ge=1, le=90)
    total_verification_requests: int = Field(ge=0)
    requests_by_status: dict[str, int]
    pending_review_count: int = Field(ge=0)
    priority_case_count: int = Field(ge=0)
    recent_cases: list[AdminOverviewCase]
    recent_admin_activity: list[AdminOverviewActivity]
    organization_total: int = Field(ge=0)
    registry_total: int = Field(ge=0)
    user_total: int | None = Field(default=None, ge=0)
