"""Email delivery adapters — console (dev) or SMTP (real inboxes)."""

from __future__ import annotations

import logging
from typing import Protocol

from app.config import Settings, get_settings
from app.integrations.email.smtp import SmtpEmailSender
from app.integrations.email.ses import SesEmailSender

logger = logging.getLogger(__name__)


class EmailSender(Protocol):
    async def send_signup_otp(self, *, to_email: str, code: str, ttl_minutes: int) -> None: ...

    async def send_password_reset(self, *, to_email: str, reset_token: str, ttl_minutes: int) -> None: ...

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
    ) -> None: ...


class ConsoleEmailSender:
    """Log OTP to structured logs — use only for local development."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def send_signup_otp(self, *, to_email: str, code: str, ttl_minutes: int) -> None:
        extra: dict[str, object] = {
            "event": "signup_otp_email",
            "to_email_domain": to_email.split("@")[-1] if "@" in to_email else "unknown",
            "ttl_minutes": ttl_minutes,
        }
        if not self._settings.is_production:
            extra["otp_code"] = code
        logger.info("signup_otp_email", extra=extra)

    async def send_password_reset(self, *, to_email: str, reset_token: str, ttl_minutes: int) -> None:
        extra: dict[str, object] = {
            "event": "password_reset_email",
            "to_email_domain": to_email.split("@")[-1] if "@" in to_email else "unknown",
            "ttl_minutes": ttl_minutes,
        }
        logger.info("password_reset_email", extra=extra)

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
        extra: dict[str, object] = {
            "event": "employer_verification_email",
            "to_email_domain": to_email.split("@")[-1] if "@" in to_email else "unknown",
            "ttl_hours": ttl_hours,
        }
        if not self._settings.is_production:
            extra["review_url"] = review_url
        logger.info("employer_verification_email", extra=extra)


def get_email_sender(settings: Settings | None = None) -> EmailSender:
    s = settings or get_settings()
    backend = s.email_backend.lower().strip()
    if backend == "smtp":
        return SmtpEmailSender(s)
    if backend == "ses":
        return SesEmailSender(s)
    if backend != "console":
        logger.warning("unknown_email_backend", extra={"email_backend": backend})
    return ConsoleEmailSender(s)
