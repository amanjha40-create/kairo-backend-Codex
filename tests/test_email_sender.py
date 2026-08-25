"""Unit tests for the business-facing email sender facade."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.config import Settings
from app.exceptions import ServiceUnavailableError
from app.integrations.email.sender import ProviderEmailSender
from app.models.email_delivery_log import EmailDeliveryLog
from app.schemas.email_delivery import EmailSendResult, RenderedEmailMessage


def _settings(**overrides: object) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        "jwt_secret_key": "test-jwt-secret-key-32-chars-minimum!!",
        "email_backend": "console",
        "brevo_api_key": "test-brevo-key",
    }
    base.update(overrides)
    return Settings(**base)


class FakeProvider:
    def __init__(self, *, exc: Exception | None = None) -> None:
        self.exc = exc
        self.messages: list[RenderedEmailMessage] = []

    async def send(self, message: RenderedEmailMessage) -> EmailSendResult:
        self.messages.append(message)
        if self.exc is not None:
            raise self.exc
        return EmailSendResult(
            provider="fake",
            status="sent",
            provider_message_id="fake-message-id",
        )


class FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.flushed = False

    async def flush(self) -> None:
        self.flushed = True

    async def commit(self) -> None:
        self.committed = True


class FakeEmailDeliveryLogRepository:
    def __init__(self) -> None:
        self.created: EmailDeliveryLog | None = None

    async def create(self, log: EmailDeliveryLog) -> EmailDeliveryLog:
        if log.public_id is None:
            log.public_id = uuid4()
        self.created = log
        return log


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sender_call", "expected_template_key", "expected_phrase"),
    [
        (
            lambda sender: sender.send_signup_otp(
                to_email="recipient@example.com",
                code="123456",
                ttl_minutes=10,
            ),
            "signup_otp",
            "verification code",
        ),
        (
            lambda sender: sender.send_password_reset(
                to_email="recipient@example.com",
                reset_token="reset-token",
                ttl_minutes=15,
            ),
            "password_reset",
            "password reset token",
        ),
        (
            lambda sender: sender.send_admin_invitation(
                to_email="recipient@example.com",
                invited_role_label="Support",
                invitation_url="https://admin.example.com/admin/accept-invitation#token=single-use-token",
                expires_at=datetime(2026, 8, 30, tzinfo=UTC),
            ),
            "admin_invitation",
            "accept admin invitation",
        ),
        (
            lambda sender: sender.send_employer_verification(
                to_email="recipient@example.com",
                contact_name="Reviewer",
                subject_full_name="Candidate",
                employer_name="Example Company",
                job_title="Engineer",
                relationship="HR",
                review_url="https://example.com/verify/token",
                ttl_hours=72,
            ),
            "employer_verification",
            "verify their employment",
        ),
        (
            lambda sender: sender.send_institution_verification(
                to_email="recipient@example.com",
                contact_name="Registrar",
                subject_name="Candidate",
                institution_name="Kairo University",
                degree="BSc",
                programme="Computer Science",
                review_url="https://example.com/institution/verify/token",
                ttl_hours=72,
            ),
            "institution_verification",
            "review an education claim",
        ),
    ],
)
async def test_provider_email_sender_renders_supported_transactional_flows(
    sender_call: Callable[[ProviderEmailSender], object],
    expected_template_key: str,
    expected_phrase: str,
) -> None:
    provider = FakeProvider()
    sender = ProviderEmailSender(_settings(), provider=provider)

    await sender_call(sender)

    assert len(provider.messages) == 1
    message = provider.messages[0]
    assert message.template_key == expected_template_key
    assert expected_phrase in message.text_body.lower()


@pytest.mark.asyncio
async def test_provider_email_sender_preserves_signup_failure_message() -> None:
    sender = ProviderEmailSender(
        _settings(),
        provider=FakeProvider(exc=ServiceUnavailableError("Unable to send email")),
    )

    with pytest.raises(ServiceUnavailableError, match="Unable to send verification email"):
        await sender.send_signup_otp(
            to_email="recipient@example.com",
            code="123456",
            ttl_minutes=10,
        )


@pytest.mark.asyncio
async def test_provider_email_sender_preserves_password_reset_failure_message() -> None:
    sender = ProviderEmailSender(
        _settings(),
        provider=FakeProvider(exc=ServiceUnavailableError("Unable to send email")),
    )

    with pytest.raises(ServiceUnavailableError, match="Unable to send password reset email"):
        await sender.send_password_reset(
            to_email="recipient@example.com",
            reset_token="reset-token",
            ttl_minutes=15,
        )


@pytest.mark.asyncio
async def test_provider_email_sender_preserves_verification_outreach_failure_message() -> None:
    sender = ProviderEmailSender(
        _settings(),
        provider=FakeProvider(exc=ServiceUnavailableError("Unable to send email")),
    )

    with pytest.raises(ServiceUnavailableError, match="Unable to send employer verification email"):
        await sender.send_employer_verification(
            to_email="recipient@example.com",
            contact_name="Reviewer",
            subject_full_name="Candidate",
            employer_name="Example Company",
            job_title="Engineer",
            relationship="HR",
            review_url="https://example.com/verify/token",
            ttl_hours=72,
        )


@pytest.mark.asyncio
async def test_provider_email_sender_preserves_institution_verification_failure_message() -> None:
    sender = ProviderEmailSender(
        _settings(),
        provider=FakeProvider(exc=ServiceUnavailableError("Unable to send email")),
    )

    with pytest.raises(
        ServiceUnavailableError,
        match="Unable to send institution verification email",
    ):
        await sender.send_institution_verification(
            to_email="recipient@example.com",
            contact_name="Registrar",
            subject_name="Candidate",
            institution_name="Kairo University",
            degree="BSc",
            programme="Computer Science",
            review_url="https://example.com/institution/verify/token",
            ttl_hours=72,
        )


@pytest.mark.asyncio
async def test_provider_email_sender_persists_signup_delivery_log_when_session_available() -> None:
    provider = FakeProvider()
    session = FakeSession()
    logs = FakeEmailDeliveryLogRepository()
    sender = ProviderEmailSender(
        _settings(email_backend="brevo"),
        session=session,  # type: ignore[arg-type]
        provider=provider,
        logs=logs,  # type: ignore[arg-type]
    )

    await sender.send_signup_otp(
        to_email="recipient@example.com",
        code="123456",
        ttl_minutes=10,
    )

    assert session.flushed is True
    assert session.committed is False
    assert logs.created is not None
    assert logs.created.status == "sent"
    assert logs.created.provider == "fake"
    assert logs.created.provider_message_id == "fake-message-id"
    assert logs.created.payload == {"ttl_minutes": 10}
    assert "code" not in logs.created.payload


@pytest.mark.asyncio
async def test_provider_email_sender_commits_failed_signup_delivery_log_when_provider_fails() -> (
    None
):
    session = FakeSession()
    logs = FakeEmailDeliveryLogRepository()
    sender = ProviderEmailSender(
        _settings(email_backend="brevo"),
        session=session,  # type: ignore[arg-type]
        provider=FakeProvider(exc=ServiceUnavailableError("Unable to send email")),
        logs=logs,  # type: ignore[arg-type]
    )

    with pytest.raises(ServiceUnavailableError, match="Unable to send verification email"):
        await sender.send_signup_otp(
            to_email="recipient@example.com",
            code="123456",
            ttl_minutes=10,
        )

    assert session.committed is True
    assert logs.created is not None
    assert logs.created.status == "failed"
    assert logs.created.error_code == "ServiceUnavailableError"


@pytest.mark.asyncio
async def test_provider_email_sender_merges_safe_audit_metadata_into_delivery_log() -> None:
    provider = FakeProvider()
    session = FakeSession()
    logs = FakeEmailDeliveryLogRepository()
    sender = ProviderEmailSender(
        _settings(email_backend="brevo"),
        session=session,  # type: ignore[arg-type]
        provider=provider,
        logs=logs,  # type: ignore[arg-type]
    )

    await sender.send_employer_verification(
        to_email="recipient@example.com",
        contact_name="Reviewer",
        subject_full_name="Candidate",
        employer_name="Example Company",
        job_title="Engineer",
        relationship="HR",
        review_url="https://example.com/verify/token",
        ttl_hours=72,
        audit_metadata={
            "verification_request_public_id": "11111111-1111-1111-1111-111111111111",
            "employer_verification_request_public_id": "22222222-2222-2222-2222-222222222222",
        },
    )

    assert logs.created is not None
    assert logs.created.payload == {
        "contact_name": "Reviewer",
        "subject_full_name": "Candidate",
        "employer_name": "Example Company",
        "job_title": "Engineer",
        "relationship": "HR",
        "ttl_hours": 72,
        "verification_request_public_id": "11111111-1111-1111-1111-111111111111",
        "employer_verification_request_public_id": "22222222-2222-2222-2222-222222222222",
    }
