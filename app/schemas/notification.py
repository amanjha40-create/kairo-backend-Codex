"""Notification center DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_key(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("value cannot be empty")
    return normalized


class NotificationPreferenceUpsertRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    event_type: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    preferred_channels: list[str] = Field(default_factory=list)
    quiet_hours: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str) -> str:
        return _normalize_key(value)

    @field_validator("preferred_channels")
    @classmethod
    def validate_preferred_channels(cls, value: list[str]) -> list[str]:
        return [_normalize_key(item) for item in value]


class NotificationDeliveryResponse(BaseModel):
    public_id: UUID
    channel: str
    status: str
    provider: str | None
    provider_message_id: str | None
    email_delivery_log_public_id: UUID | None = None
    attempt_count: int
    error_code: str | None
    error_message: str | None
    metadata: dict[str, Any]
    dispatched_at: datetime | None
    delivered_at: datetime | None
    failed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class NotificationEventResponse(BaseModel):
    public_id: UUID
    actor_user_id: UUID | None
    event_type: str
    status: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class NotificationPreferenceResponse(BaseModel):
    public_id: UUID
    user_id: UUID
    event_type: str
    enabled: bool
    preferred_channels: list[str]
    quiet_hours: dict[str, Any]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class NotificationResponse(BaseModel):
    public_id: UUID
    notification_type: str
    event_type: str
    category: str = "system"
    title: str = "Kairo notification"
    body: str = "You have a new notification."
    priority: str
    status: str
    recipient_user_id: UUID | None
    recipient_email: str | None
    recipient_phone: str | None
    channel: str
    template_key: str
    template_version: str
    payload: dict[str, Any]
    metadata: dict[str, Any]
    scheduled_at: datetime | None
    sent_at: datetime | None
    failed_at: datetime | None
    read_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class UserNotificationResponse(BaseModel):
    public_id: UUID
    category: str
    event_type: str
    title: str
    body: str
    metadata: dict[str, Any]
    read_at: datetime | None
    created_at: datetime


class NotificationUnreadCountResponse(BaseModel):
    unread_count: int


class NotificationDetailResponse(NotificationResponse):
    deliveries: list[NotificationDeliveryResponse]
    history: list[NotificationEventResponse]


class NotificationStatisticsResponse(BaseModel):
    total_notifications: int
    by_status: dict[str, int]
    by_channel: dict[str, int]
