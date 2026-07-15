"""Amazon SES-backed generic email provider."""

from __future__ import annotations

import asyncio
from email.message import EmailMessage
import logging
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from app.config import Settings, get_settings
from app.exceptions import ServiceUnavailableError
from app.integrations.email.ses import send_message_via_ses
from app.schemas.email_delivery import EmailSendResult, RenderedEmailMessage

logger = logging.getLogger(__name__)


class SesEmailProvider:
    provider_name = "ses"

    def __init__(self, settings: Settings | None = None, *, client: Any | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client

    async def send(self, message: RenderedEmailMessage) -> EmailSendResult:
        if not self._settings.email_send_enabled:
            logger.info(
                "email_delivery_ses_skipped",
                extra={
                    "event": "email_delivery_ses_skipped",
                    "template_key": message.template_key,
                    "template_version": message.template_version,
                },
            )
            return EmailSendResult(provider=self.provider_name, status="skipped")

        email_message = EmailMessage()
        email_message["Subject"] = message.subject
        email_message["From"] = self._settings.ses_from_email or self._settings.email_from
        email_message["To"] = message.to_email
        email_message["Reply-To"] = self._settings.email_reply_to
        email_message.set_content(message.text_body)
        if message.html_body:
            email_message.add_alternative(message.html_body, subtype="html")

        try:
            message_id = await asyncio.to_thread(
                send_message_via_ses,
                self._settings,
                email_message,
                client=self._client,
            )
        except (BotoCoreError, ClientError, OSError, ServiceUnavailableError) as exc:
            logger.warning(
                "ses_send_failed",
                extra={"event": "ses_send_failed", "error_type": type(exc).__name__},
            )
            raise ServiceUnavailableError("Unable to send email") from exc

        return EmailSendResult(
            provider=self.provider_name,
            status="sent",
            provider_message_id=message_id,
        )
