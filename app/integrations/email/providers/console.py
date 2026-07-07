"""Console email provider for safe local development."""

from __future__ import annotations

import logging

from app.config import Settings, get_settings
from app.schemas.email_delivery import EmailSendResult, RenderedEmailMessage

logger = logging.getLogger(__name__)


class ConsoleEmailProvider:
    """Never sends real mail — logs safe metadata for local verification."""

    provider_name = "console"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def send(self, message: RenderedEmailMessage) -> EmailSendResult:
        extra: dict[str, object] = {
            "event": "email_delivery_console",
            "template_key": message.template_key,
            "template_version": message.template_version,
            "to_email_domain": message.to_email.split("@")[-1] if "@" in message.to_email else "unknown",
            "email_send_enabled": self._settings.email_send_enabled,
        }
        if self._settings.email_dev_log_secrets and not self._settings.is_production:
            extra["text_body"] = message.text_body
        logger.info("email_delivery_console", extra=extra)
        status = "sent" if self._settings.email_send_enabled else "skipped"
        return EmailSendResult(provider=self.provider_name, status=status)
