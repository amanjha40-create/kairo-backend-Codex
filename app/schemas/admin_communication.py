"""Admin communications operational-center DTOs."""

from __future__ import annotations

from datetime import date, datetime
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

    @field_validator("channel", "template_key", "provider")
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

