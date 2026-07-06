"""SMTP-backed generic email provider."""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.config import Settings, get_settings
from app.exceptions import ServiceUnavailableError
from app.integrations.email.smtp import send_message_via_smtp
from app.schemas.email_delivery import EmailSendResult, RenderedEmailMessage

logger = logging.getLogger(__name__)


class SmtpEmailProvider:
    provider_name = "smtp"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def send(self, message: RenderedEmailMessage) -> EmailSendResult:
        if not self._settings.email_send_enabled:
            logger.info(
                "email_delivery_smtp_skipped",
                extra={
                    "event": "email_delivery_smtp_skipped",
                    "template_key": message.template_key,
                    "template_version": message.template_version,
                },
            )
            return EmailSendResult(provider=self.provider_name, status="skipped")

        email_message = EmailMessage()
        email_message["Subject"] = message.subject
        email_message["From"] = self._settings.email_from
        email_message["To"] = message.to_email
        email_message.set_content(message.text_body)
        if message.html_body:
            email_message.add_alternative(message.html_body, subtype="html")

        try:
            await asyncio.to_thread(send_message_via_smtp, self._settings, email_message)
        except ServiceUnavailableError:
            raise
        except smtplib.SMTPException as exc:
            logger.warning(
                "smtp_send_failed",
                extra={"event": "smtp_send_failed", "error_type": type(exc).__name__},
            )
            raise ServiceUnavailableError("Unable to send email") from exc
        except OSError as exc:
            logger.warning(
                "smtp_connect_failed",
                extra={"event": "smtp_connect_failed", "error_type": type(exc).__name__},
            )
            raise ServiceUnavailableError("Unable to send email") from exc

        return EmailSendResult(provider=self.provider_name, status="sent")
