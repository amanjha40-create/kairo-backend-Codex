"""Business-facing transactional email sender backed by the provider boundary."""

from __future__ import annotations

from typing import Protocol

from app.config import Settings, get_settings
from app.exceptions import ServiceUnavailableError
from app.integrations.email.providers import get_email_provider
from app.integrations.email.providers.base import EmailProvider
from app.integrations.email.renderer import EmailTemplateRenderer
from app.integrations.email.templates import EmailTemplateKey


class EmailSender(Protocol):
    async def send_signup_otp(self, *, to_email: str, code: str, ttl_minutes: int) -> None: ...

    async def send_password_reset(
        self,
        *,
        to_email: str,
        reset_token: str,
        ttl_minutes: int,
    ) -> None: ...

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


class ProviderEmailSender:
    """Compatibility facade for auth/outreach flows using the shared provider stack."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        renderer: EmailTemplateRenderer | None = None,
        provider: EmailProvider | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._renderer = renderer or EmailTemplateRenderer()
        self._provider = provider or get_email_provider(self._settings)

    async def send_signup_otp(self, *, to_email: str, code: str, ttl_minutes: int) -> None:
        try:
            await self._provider.send(
                self._renderer.render(
                    template_key=EmailTemplateKey.SIGNUP_OTP.value,
                    to_email=to_email,
                    data={"code": code, "ttl_minutes": ttl_minutes},
                )
            )
        except ServiceUnavailableError as exc:
            raise ServiceUnavailableError("Unable to send verification email") from exc

    async def send_password_reset(
        self,
        *,
        to_email: str,
        reset_token: str,
        ttl_minutes: int,
    ) -> None:
        try:
            await self._provider.send(
                self._renderer.render(
                    template_key=EmailTemplateKey.PASSWORD_RESET.value,
                    to_email=to_email,
                    data={"reset_token": reset_token, "ttl_minutes": ttl_minutes},
                )
            )
        except ServiceUnavailableError as exc:
            raise ServiceUnavailableError("Unable to send password reset email") from exc

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
        try:
            await self._provider.send(
                self._renderer.render(
                    template_key=EmailTemplateKey.EMPLOYER_VERIFICATION.value,
                    to_email=to_email,
                    data={
                        "contact_name": contact_name,
                        "subject_full_name": subject_full_name,
                        "employer_name": employer_name,
                        "job_title": job_title,
                        "relationship": relationship,
                        "review_url": review_url,
                        "ttl_hours": ttl_hours,
                    },
                )
            )
        except ServiceUnavailableError as exc:
            raise ServiceUnavailableError("Unable to send employer verification email") from exc


def get_email_sender(settings: Settings | None = None) -> EmailSender:
    return ProviderEmailSender(settings)


ConsoleEmailSender = ProviderEmailSender
