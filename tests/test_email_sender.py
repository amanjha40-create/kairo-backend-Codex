"""Unit tests for the business-facing email sender facade."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from app.config import Settings
from app.exceptions import ServiceUnavailableError
from app.integrations.email.sender import ProviderEmailSender
from app.schemas.email_delivery import EmailSendResult, RenderedEmailMessage


def _settings(**overrides: object) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        "jwt_secret_key": "test-jwt-secret-key-32-chars-minimum!!",
        "email_backend": "console",
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
