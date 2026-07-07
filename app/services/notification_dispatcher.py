"""Dispatch orchestration for notification channels."""

from __future__ import annotations

from app.exceptions import ServiceUnavailableError
from app.models.notification import Notification
from app.notifications.contracts import NotificationDispatchOutcome
from app.services.notification_channel_registry import NotificationChannelRegistry


class NotificationDispatcher:
    """Dispatches a notification via the registered channel handler."""

    def __init__(self, registry: NotificationChannelRegistry) -> None:
        self._registry = registry

    async def dispatch(self, notification: Notification) -> NotificationDispatchOutcome:
        handler = self._registry.get_handler(notification.channel)
        if handler is None:
            raise ServiceUnavailableError(f"No notification channel handler is registered for {notification.channel}")
        return await handler.send(notification)
