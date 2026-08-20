"""Admin communications operational-center DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.pagination import ListQueryParams


class AdminCommunicationListParams(ListQueryParams):
    model_config = ConfigDict(str_strip_whitespace=True)

    channel: str | None = Field(default=None, description="Optional communication channel filter.")
    template_key: str | None = Field(
        default=None,
        description="Optional template/event key filter. Comma-separated values are supported.",
    )
    provider: str | None = Field(default=None, description="Optional provider filter.")
    related_candidate_public_id: str | None = Field(
        default=None,
        description=(
            "Optional candidate public ID filter when the communication is linked canonically."
        ),
    )
    related_verification_public_id: str | None = Field(
        default=None,
        description=(
            "Optional verification public ID filter when the communication is linked canonically."
        ),
    )
    related_organization_public_id: str | None = Field(
        default=None,
        description=(
            "Optional organization public ID filter when the communication is linked canonically."
        ),
    )

    @field_validator(
        "channel",
        "template_key",
        "provider",
        "related_candidate_public_id",
        "related_verification_public_id",
        "related_organization_public_id",
    )
    @classmethod
    def normalize_filter(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        return normalized or None


class AdminCommunicationRelatedObjectResponse(BaseModel):
    kind: str
    public_id: str
    label: str | None = None


class AdminCommunicationNotificationSummaryResponse(BaseModel):
    public_id: UUID
    event_type: str
    category: str
    title: str
    status: str
    read_at: datetime | None
    created_at: datetime


class AdminCommunicationTimelineEventResponse(BaseModel):
    kind: str
    occurred_at: datetime
    detail: str
    status: str | None = None


class AdminCommunicationListItemResponse(BaseModel):
    public_id: UUID
    channel: str
    event_type: str
    template_key: str
    template_version: str
    status: str
    recipient_masked: str
    provider: str
    provider_message_id: str | None
    provider_message_id_display: str | None
    subject: str | None
    failure_reason: str | None
    queued_at: datetime
    sent_at: datetime | None
    failed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    retryable: bool = False
    retry_policy: str
    related_object: AdminCommunicationRelatedObjectResponse | None = None
    notification: AdminCommunicationNotificationSummaryResponse | None = None


class AdminCommunicationDetailResponse(AdminCommunicationListItemResponse):
    payload_summary: dict[str, Any]
    delivery_timeline: list[AdminCommunicationTimelineEventResponse]


class AdminCommunicationAttemptResponse(BaseModel):
    notification_delivery_public_id: UUID
    communication_public_id: UUID | None = None
    channel: str
    status: str
    provider: str | None
    provider_message_id_display: str | None
    attempt_count: int
    error_code: str | None
    error_message: str | None
    dispatched_at: datetime | None
    delivered_at: datetime | None
    failed_at: datetime | None
    created_at: datetime


class AdminCommunicationAuditEventResponse(BaseModel):
    public_id: UUID
    actor_user_id: UUID | None
    event_type: str
    status: str | None
    metadata: dict[str, Any]
    created_at: datetime


class AdminCommunicationFullDetailResponse(AdminCommunicationDetailResponse):
    notification_public_id: UUID | None = None
    delivery_attempts: list[AdminCommunicationAttemptResponse]
    audit_history: list[AdminCommunicationAuditEventResponse]


class AdminCommunicationResendResponse(BaseModel):
    communication: AdminCommunicationFullDetailResponse


class AdminCommunicationSummaryResponse(BaseModel):
    total: int
    queued: int
    sent: int
    failed: int
    recent_failures_24h: int
    resendable_failed: int
