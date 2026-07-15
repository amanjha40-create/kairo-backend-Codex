"""SMTP-backed generic email provider."""

from __future__ import annotations

import asyncio
import logging
import smtplib

from app.config import Settings, get_settings
from app.exceptions import ServiceUnavailableError
from app.integrations.email.smtp import send_message_via_smtp
from app.integrations.email.message import build_mime_message
from app.integrations.email.templates.base import TransactionalEmailContent
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

        email_message = build_mime_message(
            content=TransactionalEmailContent(
                subject=message.subject,
                html_body=message.html_body or "",
                text_body=message.text_body,
            ),
            to_email=message.to_email,
            from_email=self._settings.email_from,
            reply_to=self._settings.email_reply_to,
        )

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
