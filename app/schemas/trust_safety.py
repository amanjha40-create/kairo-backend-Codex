"""Trust & Safety API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.admin_directory import AdminUserDetailResponse
from app.schemas.admin_review_workflow import (
    AdminReviewDetailResponse,
    AdminReviewTimelineResponse,
)
from app.schemas.pagination import ListQueryParams, Page
from app.schemas.trust_registry import TrustRegistryAdminDetailResponse

TrustSafetySubjectType = Literal["user", "verification_request", "trust_registry_record"]
TrustSafetySeverity = Literal["low", "medium", "high", "critical"]
TrustSafetyInvestigationStatus = Literal[
    "open",
    "in_review",
    "awaiting_information",
    "resolved",
    "dismissed",
]
TrustSafetySignalStatus = Literal["active", "resolved"]


class TrustSafetyListParams(ListQueryParams):
    status: str | None = None
    severity: str | None = None
    subject_type: str | None = None
    subject_public_id: UUID | None = None
    assignee_user_id: UUID | None = None
    source: str | None = None


class RiskSignalResponse(BaseModel):
    public_id: UUID
    signal_type: str
    subject_type: TrustSafetySubjectType
    subject_public_id: UUID
    severity: TrustSafetySeverity
    source: str
    summary: str
    metadata: dict[str, object]
    status: TrustSafetySignalStatus
    detected_at: datetime
    resolved_at: datetime | None
    investigation_public_id: UUID | None = None


class TrustSafetyInvestigationAssigneeResponse(BaseModel):
    user_id: UUID
    full_name: str | None = None
    email: str
    role: str


class TrustSafetyInvestigationListItemResponse(BaseModel):
    public_id: UUID
    title: str
    summary: str
    status: TrustSafetyInvestigationStatus
    severity: TrustSafetySeverity
    subject_type: TrustSafetySubjectType
    subject_public_id: UUID
    subject_label: str
    primary_signal_summary: str | None = None
    assignee: TrustSafetyInvestigationAssigneeResponse | None = None
    created_at: datetime
    updated_at: datetime


class TrustSafetyInvestigationNoteResponse(BaseModel):
    public_id: UUID
    author_user_id: UUID | None
    author_display_name: str | None
    body: str
    metadata: dict[str, object]
    created_at: datetime


class TrustSafetyInvestigationEventResponse(BaseModel):
    public_id: UUID
    actor_user_id: UUID | None
    actor_display_name: str | None
    event_type: str
    detail: str | None
    metadata: dict[str, object]
    created_at: datetime


class TrustSafetySubjectContextResponse(BaseModel):
    user: AdminUserDetailResponse | None = None
    verification: AdminReviewDetailResponse | None = None
    verification_timeline: AdminReviewTimelineResponse | None = None
    registry: TrustRegistryAdminDetailResponse | None = None


class TrustSafetyInvestigationDetailResponse(BaseModel):
    public_id: UUID
    title: str
    summary: str
    status: TrustSafetyInvestigationStatus
    severity: TrustSafetySeverity
    subject_type: TrustSafetySubjectType
    subject_public_id: UUID
    subject_label: str
    assignee: TrustSafetyInvestigationAssigneeResponse | None = None
    created_by_user_id: UUID | None = None
    resolved_by_user_id: UUID | None = None
    resolved_at: datetime | None = None
    resolution_reason: str | None = None
    dismissed_at: datetime | None = None
    dismissed_by_user_id: UUID | None = None
    dismissal_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    signals: list[RiskSignalResponse] = Field(default_factory=list)
    notes: list[TrustSafetyInvestigationNoteResponse] = Field(default_factory=list)
    timeline: list[TrustSafetyInvestigationEventResponse] = Field(default_factory=list)
    subject_context: TrustSafetySubjectContextResponse = Field(
        default_factory=TrustSafetySubjectContextResponse
    )


class TrustSafetyCreateInvestigationRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    subject_type: TrustSafetySubjectType
    subject_public_id: UUID
    summary: str = Field(min_length=1, max_length=5000)
    severity: TrustSafetySeverity
    signal_type: str = Field(default="manual_review", min_length=1, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=255)


class TrustSafetyAssignInvestigationRequest(BaseModel):
    assignee_user_id: UUID


class TrustSafetyUpdateSeverityRequest(BaseModel):
    severity: TrustSafetySeverity


class TrustSafetyAddNoteRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    body: str = Field(min_length=1, max_length=5000)
    metadata: dict[str, object] = Field(default_factory=dict)


class TrustSafetyUpdateStatusRequest(BaseModel):
    status: Literal["open", "in_review", "awaiting_information"]
    reason: str | None = Field(default=None, max_length=5000)


class TrustSafetyResolveRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(min_length=1, max_length=5000)


class TrustSafetyDismissRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(min_length=1, max_length=5000)


class TrustSafetyOverviewSummaryResponse(BaseModel):
    open_investigations: int = Field(ge=0)
    high_or_critical_investigations: int = Field(ge=0)
    unassigned_investigations: int = Field(ge=0)
    active_signals: int = Field(ge=0)


TrustSafetySignalPage = Page[RiskSignalResponse]
TrustSafetyInvestigationPage = Page[TrustSafetyInvestigationListItemResponse]
