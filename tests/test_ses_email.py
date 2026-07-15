"""Amazon SES compatibility sender tests."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.integrations.email.sender import get_email_sender
from app.integrations.email.ses import SesEmailSender


class _FakeSesClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def send_email(self, **kwargs: object) -> dict[str, str]:
        self.requests.append(kwargs)
        return {"MessageId": f"ses-message-{len(self.requests)}"}


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        "jwt_secret_key": "test-jwt-secret-key-32-chars-minimum!!",
        "email_backend": "ses",
        "email_send_enabled": True,
        "aws_region": "us-east-1",
        "ses_from_email": "verify@kairoid.com",
    }
    values.update(overrides)
    return Settings(**values)


def test_sender_factory_selects_ses() -> None:
    assert isinstance(get_email_sender(_settings()), SesEmailSender)


@pytest.mark.asyncio
async def test_ses_sender_uses_existing_transactional_templates() -> None:
    client = _FakeSesClient()
    sender = SesEmailSender(_settings(), client=client)

    await sender.send_signup_otp(to_email="recipient@example.com", code="123456", ttl_minutes=10)
    await sender.send_password_reset(
        to_email="recipient@example.com",
        reset_token="reset-token",
        ttl_minutes=15,
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
    )

    assert len(client.requests) == 3
    raw_messages = [request["Content"]["Raw"]["Data"] for request in client.requests]  # type: ignore[index]
    assert b"verification code" in raw_messages[0]
    assert b"password" in raw_messages[1]
    assert b"employment verification" in raw_messages[2]
    assert all(request["FromEmailAddress"] == "verify@kairoid.com" for request in client.requests)


@pytest.mark.asyncio
async def test_ses_sender_does_not_send_when_delivery_disabled() -> None:
    client = _FakeSesClient()
    sender = SesEmailSender(_settings(email_send_enabled=False), client=client)

    await sender.send_signup_otp(to_email="recipient@example.com", code="123456", ttl_minutes=10)

    assert client.requests == []
