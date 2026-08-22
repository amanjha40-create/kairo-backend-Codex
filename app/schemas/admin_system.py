"""Admin System Operations DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.pagination import Page, PageParams

SystemHealthState = Literal["healthy", "degraded", "unavailable", "unknown"]
SystemIncidentSeverity = Literal["low", "medium", "high", "critical"]
SystemIncidentStatus = Literal["open", "monitoring", "resolved"]


class AdminSystemStatusDependencyResponse(BaseModel):
    key: str
    name: str
    status: SystemHealthState
    checked_at: datetime
    critical: bool = False
    latency_ms: int | None = Field(default=None, ge=0)
    reason: str | None = None


class AdminSystemStatusResponse(BaseModel):
    overall_status: SystemHealthState
    checked_at: datetime
    dependencies: list[AdminSystemStatusDependencyResponse]


class AdminSystemMigrationStatusResponse(BaseModel):
    current_revision: str | None = None
    expected_revision: str | None = None
    matches_expected: bool
    multiple_heads: bool = False


class AdminSystemReleaseResponse(BaseModel):
    git_sha: str | None = None
    build_id: str | None = None
    deployed_at: str | None = None


class AdminSystemRuntimeResponse(BaseModel):
    environment: str
    application_name: str
    application_version: str
    api_version_prefix: str
    runtime_started_at: datetime
    checked_at: datetime
    python_version: str
    job_backend: str
    resume_processing_enabled: bool
    email_backend: str
    email_send_enabled: bool
    phone_otp_backend: str
    release: AdminSystemReleaseResponse
    migration: AdminSystemMigrationStatusResponse


class AdminSystemWorkloadSummaryResponse(BaseModel):
    key: str
    name: str
    status: SystemHealthState
    pending: int = Field(ge=0)
    processing: int = Field(ge=0)
    succeeded_recent: int = Field(ge=0)
    failed: int = Field(ge=0)
    retryable: int = Field(ge=0)
    oldest_pending_at: datetime | None = None
    latest_success_at: datetime | None = None
    latest_failure_at: datetime | None = None
    note: str | None = None


class AdminSystemWorkloadsResponse(BaseModel):
    generated_at: datetime
    workloads: list[AdminSystemWorkloadSummaryResponse]


class AdminSystemFailureItemResponse(BaseModel):
    kind: str
    public_id: UUID
    category: str
    subject_reference: str
    title: str
    status: str
    first_failure_at: datetime
    latest_failure_at: datetime
    retry_count: int = Field(ge=0)
    safe_error: str | None = None
    retry_supported: bool = False
    retry_reference: str | None = None


class AdminSystemFailuresResponse(BaseModel):
    generated_at: datetime
    items: list[AdminSystemFailureItemResponse]


class AdminSystemActivityItemResponse(BaseModel):
    kind: str
    public_id: UUID
    occurred_at: datetime
    title: str
    detail: str | None = None
    status: str | None = None
    actor_user_id: UUID | None = None
    subject_type: str | None = None
    subject_public_id: UUID | None = None


class AdminSystemActivityParams(PageParams):
    pass


class AdminSystemIncidentListParams(PageParams):
    model_config = ConfigDict(str_strip_whitespace=True)

    status: SystemIncidentStatus | Literal["all"] = "all"
    severity: SystemIncidentSeverity | Literal["all"] = "all"
    category: str | Literal["all"] = "all"


class AdminSystemIncidentEventResponse(BaseModel):
    public_id: UUID
    actor_user_id: UUID | None = None
    event_type: str
    detail: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class AdminSystemIncidentListItemResponse(BaseModel):
    public_id: UUID
    title: str
    summary: str
    category: str
    severity: SystemIncidentSeverity
    status: SystemIncidentStatus
    source: str
    opened_at: datetime
    resolved_at: datetime | None = None
    created_by_user_id: UUID | None = None
    resolved_by_user_id: UUID | None = None
    reference_type: str | None = None
    reference_public_id: UUID | None = None
    updated_at: datetime


class AdminSystemIncidentDetailResponse(AdminSystemIncidentListItemResponse):
    history: list[AdminSystemIncidentEventResponse] = Field(default_factory=list)


class AdminSystemCreateIncidentRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=255)
    summary: str = Field(min_length=1, max_length=5000)
    category: str = Field(min_length=1, max_length=64)
    severity: SystemIncidentSeverity
    reference_type: str | None = Field(default=None, max_length=64)
    reference_public_id: UUID | None = None


class AdminSystemUpdateIncidentRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=255)
    summary: str | None = Field(default=None, min_length=1, max_length=5000)
    category: str | None = Field(default=None, min_length=1, max_length=64)
    severity: SystemIncidentSeverity | None = None
    status: Literal["open", "monitoring"] | None = None


class AdminSystemResolveIncidentRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(min_length=1, max_length=5000)


class AdminSystemRetryResponse(BaseModel):
    operation: str
    reference_public_id: UUID
    message: str
    subject_public_id: UUID | None = None


AdminSystemIncidentPage = Page[AdminSystemIncidentListItemResponse]
AdminSystemActivityPage = Page[AdminSystemActivityItemResponse]
