"""Business-facing transactional email sender backed by the provider boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.exceptions import ServiceUnavailableError
from app.integrations.email.providers import get_email_provider
from app.integrations.email.providers.base import EmailProvider
from app.integrations.email.renderer import EmailTemplateRenderer
from app.integrations.email.templates import EmailTemplateKey
from app.models.email_delivery_log import EmailDeliveryLog
from app.repositories.email_delivery_log import EmailDeliveryLogRepository
from app.schemas.email_delivery import RenderedEmailMessage


class EmailSender(Protocol):
    async def send_signup_otp(
        self,
        *,
        to_email: str,
        code: str,
        ttl_minutes: int,
        audit_metadata: dict[str, object] | None = None,
    ) -> None: ...

    async def send_password_reset(
        self,
        *,
        to_email: str,
        reset_token: str,
        ttl_minutes: int,
        reset_url: str | None = None,
        audit_metadata: dict[str, object] | None = None,
    ) -> None: ...

    async def send_admin_invitation(
        self,
        *,
        to_email: str,
        invited_role_label: str,
        invitation_url: str,
        expires_at: datetime,
        audit_metadata: dict[str, object] | None = None,
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
        audit_metadata: dict[str, object] | None = None,
    ) -> None: ...

    async def send_institution_verification(
        self,
        *,
        to_email: str,
        contact_name: str,
        subject_name: str,
        institution_name: str,
        degree: str,
        programme: str,
        review_url: str,
        ttl_hours: int,
        audit_metadata: dict[str, object] | None = None,
    ) -> None: ...


class ProviderEmailSender:
    """Compatibility facade for auth/outreach flows using the shared provider stack."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        session: AsyncSession | None = None,
        renderer: EmailTemplateRenderer | None = None,
        provider: EmailProvider | None = None,
        logs: EmailDeliveryLogRepository | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._session = session
        self._renderer = renderer or EmailTemplateRenderer()
        self._provider = provider or get_email_provider(self._settings)
        self._logs = logs or (EmailDeliveryLogRepository(session) if session is not None else None)

    async def _send_rendered(
        self,
        *,
        message: RenderedEmailMessage,
        failure_message: str,
        audit_metadata: dict[str, object] | None = None,
    ) -> None:
        log: EmailDeliveryLog | None = None
        now = datetime.now(tz=UTC)
        if self._logs is not None:
            log = EmailDeliveryLog(
                template_key=message.template_key,
                template_version=message.template_version,
                recipient_email=message.to_email,
                provider=getattr(self._provider, "provider_name", self._settings.email_backend),
                status="pending",
                subject=message.subject,
                payload={**message.audit_payload, **(audit_metadata or {})},
                attempt_count=1,
            )
            await self._logs.create(log)

        try:
            result = await self._provider.send(message)
        except ServiceUnavailableError as exc:
            if log is not None and self._session is not None:
                log.status = "failed"
                log.failed_at = now
                log.error_code = type(exc).__name__
                log.error_message = str(exc)
                await self._session.commit()
            raise ServiceUnavailableError(failure_message) from exc

        if log is not None:
            log.provider = result.provider or log.provider
            log.status = result.status
            log.provider_message_id = result.provider_message_id
            log.error_code = result.error_code
            log.error_message = result.error_message
            if result.status == "sent":
                log.sent_at = now
            if result.status == "failed":
                log.failed_at = now
            if self._session is not None:
                await self._session.flush()

    async def send_signup_otp(
        self,
        *,
        to_email: str,
        code: str,
        ttl_minutes: int,
        audit_metadata: dict[str, object] | None = None,
    ) -> None:
        try:
            await self._send_rendered(
                message=self._renderer.render(
                    template_key=EmailTemplateKey.SIGNUP_OTP.value,
                    to_email=to_email,
                    data={"code": code, "ttl_minutes": ttl_minutes},
                ),
                failure_message="Unable to send verification email",
                audit_metadata=audit_metadata,
            )
        except ServiceUnavailableError:
            raise

    async def send_password_reset(
        self,
        *,
        to_email: str,
        reset_token: str,
        ttl_minutes: int,
        reset_url: str | None = None,
        audit_metadata: dict[str, object] | None = None,
    ) -> None:
        try:
            await self._send_rendered(
                message=self._renderer.render(
                    template_key=EmailTemplateKey.PASSWORD_RESET.value,
                    to_email=to_email,
                    data={
                        "reset_token": reset_token,
                        "ttl_minutes": ttl_minutes,
                        "reset_url": reset_url,
                    },
                ),
                failure_message="Unable to send password reset email",
                audit_metadata=audit_metadata,
            )
        except ServiceUnavailableError:
            raise

    async def send_admin_invitation(
        self,
        *,
        to_email: str,
        invited_role_label: str,
        invitation_url: str,
        expires_at: datetime,
        audit_metadata: dict[str, object] | None = None,
    ) -> None:
        try:
            await self._send_rendered(
                message=self._renderer.render(
                    template_key=EmailTemplateKey.ADMIN_INVITATION.value,
                    to_email=to_email,
                    data={
                        "invited_role_label": invited_role_label,
                        "invitation_url": invitation_url,
                        "expires_at_iso": expires_at.isoformat(),
                    },
                ),
                failure_message="Unable to send admin invitation email",
                audit_metadata=audit_metadata,
            )
        except ServiceUnavailableError:
            raise

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
        audit_metadata: dict[str, object] | None = None,
    ) -> None:
        try:
            await self._send_rendered(
                message=self._renderer.render(
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
                ),
                failure_message="Unable to send employer verification email",
                audit_metadata=audit_metadata,
            )
        except ServiceUnavailableError:
            raise

    async def send_institution_verification(
        self,
        *,
        to_email: str,
        contact_name: str,
        subject_name: str,
        institution_name: str,
        degree: str,
        programme: str,
        review_url: str,
        ttl_hours: int,
        audit_metadata: dict[str, object] | None = None,
    ) -> None:
        try:
            await self._send_rendered(
                message=self._renderer.render(
                    template_key=EmailTemplateKey.INSTITUTION_VERIFICATION.value,
                    to_email=to_email,
                    data={
                        "contact_name": contact_name,
                        "subject_name": subject_name,
                        "institution_name": institution_name,
                        "degree": degree,
                        "programme": programme,
                        "review_url": review_url,
                        "ttl_hours": ttl_hours,
                    },
                ),
                failure_message="Unable to send institution verification email",
                audit_metadata=audit_metadata,
            )
        except ServiceUnavailableError:
            raise


def get_email_sender(
    settings: Settings | None = None,
    *,
    session: AsyncSession | None = None,
) -> EmailSender:
    return ProviderEmailSender(settings, session=session)


ConsoleEmailSender = ProviderEmailSender
