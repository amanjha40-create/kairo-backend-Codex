"""In-app notification handler for inbox-only events."""

from __future__ import annotations

from datetime import UTC, datetime

from app.models.notification import Notification
from app.notifications.contracts import NotificationChannelHandler, NotificationDispatchOutcome
from app.notifications.enums import NotificationStatus


class NotificationInAppChannel(NotificationChannelHandler):
    """Marks a notification as delivered to the in-app inbox without external transport."""

    channel_key = "in_app"

    async def send(self, notification: Notification) -> NotificationDispatchOutcome:  # noqa: ARG002
        now = datetime.now(tz=UTC)
        return NotificationDispatchOutcome(
            status=NotificationStatus.SENT.value,
            provider="kairo_in_app",
            dispatched_at=now,
            delivered_at=now,
            attempt_count=1,
        )
