"""Channel registry for notification center."""

from __future__ import annotations

from app.notifications.contracts import NotificationChannelHandler


class NotificationChannelRegistry:
    """Maps channel keys to concrete handler implementations."""

    def __init__(
        self,
        handlers: tuple[NotificationChannelHandler, ...] | None = None,
    ) -> None:
        self._handlers = handlers or ()
        self._handler_by_key = {handler.channel_key: handler for handler in self._handlers}

    def get_handler(self, channel: str) -> NotificationChannelHandler | None:
        return self._handler_by_key.get(channel.strip().lower())
