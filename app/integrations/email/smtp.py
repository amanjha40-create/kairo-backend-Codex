"""SMTP email delivery — Gmail, Brevo, Mailgun, and other STARTTLS/SSL providers."""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.config import Settings, get_settings
from app.exceptions import ServiceUnavailableError
from app.integrations.email.employer_verification_email import build_employer_verification_email

logger = logging.getLogger(__name__)


def build_signup_otp_email(
    *,
    app_name: str,
    to_email: str,
    from_email: str,
    code: str,
    ttl_minutes: int,
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"{app_name} — verify your email"
    msg["From"] = from_email
    msg["To"] = to_email
    msg.set_content(
        f"Your verification code is: {code}\n\n"
        f"This code expires in {ttl_minutes} minutes.\n\n"
        f"If you did not request this, you can ignore this email."
    )
    return msg


def _send_message_sync(settings: Settings, message: EmailMessage) -> None:
    host = settings.smtp_host
    if not host:
        raise ServiceUnavailableError("Email is not configured")

    timeout = settings.smtp_timeout_seconds
    user = settings.smtp_user
    password = settings.smtp_password

    if settings.smtp_use_ssl:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, settings.smtp_port, timeout=timeout, context=context) as smtp:
            if user and password:
                smtp.login(user, password)
            smtp.send_message(message)
        return

    with smtplib.SMTP(host, settings.smtp_port, timeout=timeout) as smtp:
        if settings.smtp_use_tls:
            context = ssl.create_default_context()
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
        if user and password:
            smtp.login(user, password)
        smtp.send_message(message)


class SmtpEmailSender:
    """Send transactional mail via SMTP (runs blocking I/O in a worker thread)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def send_signup_otp(self, *, to_email: str, code: str, ttl_minutes: int) -> None:
        message = build_signup_otp_email(
            app_name=self._settings.app_name,
            to_email=to_email,
            from_email=self._settings.email_from,
            code=code,
            ttl_minutes=ttl_minutes,
        )
        try:
            await asyncio.to_thread(_send_message_sync, self._settings, message)
        except ServiceUnavailableError:
            raise
        except smtplib.SMTPException as exc:
            logger.warning(
                "smtp_send_failed",
                extra={
                    "event": "smtp_send_failed",
                    "error_type": type(exc).__name__,
                    "to_email_domain": to_email.split("@")[-1] if "@" in to_email else "unknown",
                },
            )
            raise ServiceUnavailableError("Unable to send verification email") from exc
        except OSError as exc:
            logger.warning(
                "smtp_connect_failed",
                extra={
                    "event": "smtp_connect_failed",
                    "error_type": type(exc).__name__,
                },
            )
            raise ServiceUnavailableError("Unable to send verification email") from exc

        logger.info(
            "signup_otp_email_sent",
            extra={
                "event": "signup_otp_email_sent",
                "to_email_domain": to_email.split("@")[-1] if "@" in to_email else "unknown",
                "ttl_minutes": ttl_minutes,
            },
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
            from_email=self._settings.email_from,
            contact_name=contact_name,
            subject_full_name=subject_full_name,
            employer_name=employer_name,
            job_title=job_title,
            relationship=relationship,
            review_url=review_url,
            expires_hours=ttl_hours,
        )
        try:
            await asyncio.to_thread(_send_message_sync, self._settings, message)
        except ServiceUnavailableError:
            raise
        except smtplib.SMTPException as exc:
            logger.warning(
                "smtp_send_failed",
                extra={
                    "event": "smtp_send_failed",
                    "error_type": type(exc).__name__,
                    "to_email_domain": to_email.split("@")[-1] if "@" in to_email else "unknown",
                },
            )
            raise ServiceUnavailableError("Unable to send employer verification email") from exc
        except OSError as exc:
            logger.warning(
                "smtp_connect_failed",
                extra={"event": "smtp_connect_failed", "error_type": type(exc).__name__},
            )
            raise ServiceUnavailableError("Unable to send employer verification email") from exc

        logger.info(
            "employer_verification_email_sent",
            extra={
                "event": "employer_verification_email_sent",
                "to_email_domain": to_email.split("@")[-1] if "@" in to_email else "unknown",
                "ttl_hours": ttl_hours,
            },
        )
