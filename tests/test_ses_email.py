"""Amazon SES compatibility sender tests."""

from __future__ import annotations

import inspect
import logging
from email import policy
from email.parser import BytesParser

import pytest

from app.config import Settings
from app.integrations.email.sender import get_email_sender
from app.integrations.email.ses import SesEmailSender, send_message_via_ses
from app.integrations.email.message import build_mime_message
from app.integrations.email.templates.base import TransactionalEmailContent


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


def test_mime_builder_uses_valid_smtp_multipart_message() -> None:
    message = build_mime_message(
        content=TransactionalEmailContent(
            subject="Résumé verification — Kairo",
            html_body="<p>HTML résumé</p>",
            text_body="Plain résumé",
        ),
        to_email="recipient@example.com",
        from_email="verify@kairoid.com",
        reply_to="support@kairoid.com",
    )
    raw = message.as_bytes()
    assert isinstance(raw, bytes)
    parsed = BytesParser(policy=policy.default).parsebytes(raw)

    assert raw.count(b"\r\n") > 10
    assert parsed["From"] == "verify@kairoid.com"
    assert parsed["To"] == "recipient@example.com"
    assert parsed["Reply-To"] == "support@kairoid.com"
    assert parsed["Date"]
    assert parsed["Message-ID"]
    assert parsed["MIME-Version"] == "1.0"
    assert parsed.get_content_type() == "multipart/alternative"
    assert parsed.get_body(preferencelist=("plain",)).get_content().replace("\r\n", "\n") == "Plain résumé\n"
    assert parsed.get_body(preferencelist=("html",)).get_content().replace("\r\n", "\n") == "<p>HTML résumé</p>\n"


@pytest.mark.parametrize("field", ["subject", "to_email", "from_email", "reply_to"])
def test_mime_builder_rejects_header_injection(field: str) -> None:
    values = {
        "subject": "Safe",
        "to_email": "recipient@example.com",
        "from_email": "verify@kairoid.com",
        "reply_to": "support@kairoid.com",
    }
    values[field] = "safe\r\nBcc: attacker@example.com"
    with pytest.raises(ValueError):
        build_mime_message(
            content=TransactionalEmailContent(
                subject=values["subject"], html_body="<p>body</p>", text_body="body"
            ),
            to_email=values["to_email"],
            from_email=values["from_email"],
            reply_to=values["reply_to"],
        )


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
    text_bodies = []
    for raw_message in raw_messages:
        parsed = BytesParser(policy=policy.default).parsebytes(raw_message)
        plain = parsed.get_body(preferencelist=("plain",))
        assert plain is not None
        text_bodies.append(plain.get_content().lower())
    assert "verification code" in text_bodies[0]
    assert "password" in text_bodies[1]
    assert "verify their employment" in text_bodies[2]
    assert all(request["FromEmailAddress"] == "verify@kairoid.com" for request in client.requests)


@pytest.mark.asyncio
async def test_ses_sender_does_not_send_when_delivery_disabled() -> None:
    client = _FakeSesClient()
    sender = SesEmailSender(_settings(email_send_enabled=False), client=client)

    await sender.send_signup_otp(to_email="recipient@example.com", code="123456", ttl_minutes=10)

    assert client.requests == []


@pytest.mark.asyncio
async def test_ses_sender_does_not_log_security_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = _FakeSesClient()
    sender = SesEmailSender(_settings(), client=client)
    otp = "otp-secret-value"
    reset_token = "reset-secret-value"

    with caplog.at_level(logging.INFO):
        await sender.send_signup_otp(to_email="recipient@example.com", code=otp, ttl_minutes=10)
        await sender.send_password_reset(
            to_email="recipient@example.com",
            reset_token=reset_token,
            ttl_minutes=15,
        )

    rendered_logs = " ".join(record.getMessage() for record in caplog.records)
    assert otp not in rendered_logs
    assert reset_token not in rendered_logs


def test_ses_transport_contains_no_transactional_business_copy() -> None:
    source = inspect.getsource(send_message_via_ses)
    assert "Verify once" not in source
    assert "verification code" not in source
    assert "reset your password" not in source
