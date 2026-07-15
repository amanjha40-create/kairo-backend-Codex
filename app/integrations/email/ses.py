"""Amazon SES transport and compatibility sender for existing transactional emails."""

from __future__ import annotations

import asyncio
from email.message import EmailMessage
import logging
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.config import Settings, get_settings
from app.exceptions import ServiceUnavailableError
from app.integrations.email.employer_verification_email import build_employer_verification_email
from app.integrations.email.smtp import build_password_reset_email, build_signup_otp_email

logger = logging.getLogger(__name__)


def send_message_via_ses(
    settings: Settings,
    message: EmailMessage,
    *,
    client: Any | None = None,
) -> str | None:
    """Send an existing MIME message unchanged through the SES v2 Raw API."""

    if not settings.aws_region or not settings.ses_from_email:
        raise ServiceUnavailableError("Email is not configured")
    ses = client or boto3.session.Session(region_name=settings.aws_region).client("sesv2")
    response = ses.send_email(
        FromEmailAddress=settings.ses_from_email,
        Destination={"ToAddresses": [str(message["To"])]},
        Content={"Raw": {"Data": message.as_bytes()}},
    )
    return response.get("MessageId")


class SesEmailSender:
    """SES implementation of the existing auth and verification email contract."""

    def __init__(self, settings: Settings | None = None, *, client: Any | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client

    async def _send(self, message: EmailMessage, *, event: str, failure_message: str) -> None:
        if not self._settings.email_send_enabled:
            logger.info(
                "ses_email_skipped", extra={"event": "ses_email_skipped", "email_event": event}
            )
            return
        try:
            message_id = await asyncio.to_thread(
                send_message_via_ses,
                self._settings,
                message,
                client=self._client,
            )
        except (BotoCoreError, ClientError, OSError, ServiceUnavailableError) as exc:
            logger.warning(
                "ses_send_failed",
                extra={
                    "event": "ses_send_failed",
                    "error_type": type(exc).__name__,
                    "email_event": event,
                },
            )
            raise ServiceUnavailableError(failure_message) from exc
        logger.info(
            "ses_email_sent",
            extra={
                "event": "ses_email_sent",
                "email_event": event,
                "provider_message_id": message_id,
            },
        )

    async def send_signup_otp(self, *, to_email: str, code: str, ttl_minutes: int) -> None:
        message = build_signup_otp_email(
            app_name=self._settings.app_name,
            to_email=to_email,
            from_email=self._settings.ses_from_email or self._settings.email_from,
            code=code,
            ttl_minutes=ttl_minutes,
        )
        await self._send(
            message,
            event="signup_otp_email",
            failure_message="Unable to send verification email",
        )

    async def send_password_reset(
        self, *, to_email: str, reset_token: str, ttl_minutes: int
    ) -> None:
        message = build_password_reset_email(
            app_name=self._settings.app_name,
            to_email=to_email,
            from_email=self._settings.ses_from_email or self._settings.email_from,
            reset_token=reset_token,
            ttl_minutes=ttl_minutes,
        )
        await self._send(
            message,
            event="password_reset_email",
            failure_message="Unable to send password reset email",
        )

    async def send_employer_verification(
        self,
        *,
        to_email: str,
        contact_name: str,
        subject_full_name: str,
        employer_name: str,
        job_title: str,
        relationship: str,
        review_url: str,
        ttl_hours: int,
    ) -> None:
        message = build_employer_verification_email(
            app_name=self._settings.app_name,
            to_email=to_email,
            from_email=self._settings.ses_from_email or self._settings.email_from,
            contact_name=contact_name,
            subject_full_name=subject_full_name,
            employer_name=employer_name,
            job_title=job_title,
            relationship=relationship,
            review_url=review_url,
            expires_hours=ttl_hours,
        )
        await self._send(
            message,
            event="employer_verification_email",
            failure_message="Unable to send employer verification email",
        )
