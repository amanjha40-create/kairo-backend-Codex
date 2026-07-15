"""Unit tests for email providers."""

from __future__ import annotations

import pytest
from botocore.exceptions import ClientError

from app.config import Settings
from app.exceptions import ServiceUnavailableError
from app.integrations.email.providers import get_email_provider
from app.integrations.email.providers.console import ConsoleEmailProvider
from app.integrations.email.providers.ses_provider import SesEmailProvider
from app.integrations.email.providers.smtp_provider import SmtpEmailProvider
from app.schemas.email_delivery import RenderedEmailMessage


def _settings(**overrides: object) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        "jwt_secret_key": "test-jwt-secret-key-32-chars-minimum!!",
        "email_backend": "console",
    }
    base.update(overrides)
    return Settings(**base)


@pytest.mark.asyncio
async def test_console_provider_skips_when_email_send_disabled() -> None:
    provider = ConsoleEmailProvider(_settings(email_send_enabled=False))

    result = await provider.send(
        RenderedEmailMessage(
            template_key="trust_invitation",
            template_version="v1",
            to_email="aman3@test.com",
            subject="Example",
            text_body="body",
        )
    )

    assert result.provider == "console"
    assert result.status == "skipped"


def test_provider_factory_selects_console_by_default() -> None:
    provider = get_email_provider(_settings())
    assert isinstance(provider, ConsoleEmailProvider)


def test_provider_factory_selects_smtp_when_configured() -> None:
    provider = get_email_provider(
        _settings(
            email_backend="smtp",
            smtp_host="smtp.example.com",
        )
    )
    assert isinstance(provider, SmtpEmailProvider)


def test_provider_factory_selects_ses_when_configured() -> None:
    provider = get_email_provider(
        _settings(
            email_backend="ses",
            aws_region="us-east-1",
            ses_from_email="verify@kairoid.com",
        )
    )
    assert isinstance(provider, SesEmailProvider)


class _FakeSesClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def send_email(self, **kwargs: object) -> dict[str, str]:
        self.requests.append(kwargs)
        return {"MessageId": "ses-message-id"}


class _FailingSesClient:
    def send_email(self, **kwargs: object) -> dict[str, str]:
        raise ClientError(
            {"Error": {"Code": "MessageRejected", "Message": "Rejected for test"}},
            "SendEmail",
        )


@pytest.mark.asyncio
async def test_ses_provider_preserves_text_and_html_content() -> None:
    client = _FakeSesClient()
    provider = SesEmailProvider(
        _settings(
            email_backend="ses",
            email_send_enabled=True,
            aws_region="us-east-1",
            ses_from_email="verify@kairoid.com",
        ),
        client=client,
    )

    result = await provider.send(
        RenderedEmailMessage(
            template_key="trust_invitation",
            template_version="v1",
            to_email="recipient@example.com",
            subject="Example",
            text_body="Plain text fallback",
            html_body="<p>HTML body</p>",
        )
    )

    assert result.provider == "ses"
    assert result.status == "sent"
    assert result.provider_message_id == "ses-message-id"
    assert len(client.requests) == 1
    request = client.requests[0]
    assert request["FromEmailAddress"] == "verify@kairoid.com"
    assert request["Destination"] == {"ToAddresses": ["recipient@example.com"]}
    raw_message = request["Content"]["Raw"]["Data"]  # type: ignore[index]
    assert b"Reply-To: support@kairoid.com" in raw_message
    assert b"Plain text fallback" in raw_message
    assert b"HTML body" in raw_message
    assert b"multipart/alternative" in raw_message


@pytest.mark.asyncio
async def test_ses_provider_logs_and_normalizes_delivery_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = SesEmailProvider(
        _settings(
            email_backend="ses",
            email_send_enabled=True,
            aws_region="us-east-1",
            ses_from_email="verify@kairoid.com",
        ),
        client=_FailingSesClient(),
    )

    with pytest.raises(ServiceUnavailableError, match="Unable to send email"):
        await provider.send(
            RenderedEmailMessage(
                template_key="trust_invitation",
                template_version="v1",
                to_email="recipient@example.com",
                subject="Example",
                text_body="body",
            )
        )

    assert "ses_send_failed" in caplog.messages
