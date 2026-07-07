"""Contracts and internal request types for Notification Center."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from app.models.notification import Notification
from app.notifications.enums import NotificationChannel, NotificationPriority


@dataclass(slots=True)
class NotificationRequest:
    """Internal request payload for creating a notification."""

    event_type: str
    channel: str = NotificationChannel.EMAIL.value
    notification_type: str = "transactional"
    priority: str = NotificationPriority.NORMAL.value
    recipient_user_id: UUID | None = None
    recipient_email: str | None = None
    recipient_phone: str | None = None
    template_key: str | None = None
    template_version: str = "v1"
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    scheduled_at: datetime | None = None

    def normalized_event_type(self) -> str:
        return self.event_type.strip().lower()


@dataclass(slots=True)
class NotificationPreferenceDecision:
    """Result of evaluating recipient preferences for a notification."""

    enabled: bool
    selected_channel: str
    matched_preference_public_id: UUID | None = None


@dataclass(slots=True)
class NotificationDispatchOutcome:
    """Normalized channel delivery result returned by channel handlers."""

    status: str
    provider: str | None = None
    provider_message_id: str | None = None
    external_reference_id: UUID | None = None
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    dispatched_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    delivered_at: datetime | None = None
    failed_at: datetime | None = None
    attempt_count: int = 1


class NotificationChannelHandler(Protocol):
    """Pluggable channel handler contract."""

    channel_key: str

    async def send(self, notification: Notification) -> NotificationDispatchOutcome:
        """Send a notification over the handler's channel."""
