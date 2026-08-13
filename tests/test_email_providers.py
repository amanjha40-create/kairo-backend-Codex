"""Unit tests for email providers."""

from __future__ import annotations

import logging

import httpx
import pytest
from botocore.exceptions import ClientError

from app.config import Settings
from app.exceptions import ServiceUnavailableError
from app.integrations.email.providers import get_email_provider
from app.integrations.email.providers.brevo_provider import BrevoEmailProvider
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


def test_provider_factory_selects_brevo_when_configured() -> None:
    provider = get_email_provider(
        _settings(
            email_backend="brevo",
            brevo_api_key="brevo-secret",
        )
    )
    assert isinstance(provider, BrevoEmailProvider)


def test_provider_factory_rejects_unsupported_provider() -> None:
    settings = _settings()
    settings.email_backend = "unsupported"
    with pytest.raises(ValueError, match="Unsupported email provider"):
        get_email_provider(settings)


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


def _brevo_settings(**overrides: object) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        "jwt_secret_key": "test-jwt-secret-key-32-chars-minimum!!",
        "email_backend": "brevo",
        "email_send_enabled": True,
        "brevo_api_key": "brevo-secret",
        "email_from": "noreply@kairoid.com",
        "email_from_name": "Kairo",
        "email_reply_to": "support@kairoid.com",
    }
    base.update(overrides)
    return Settings(**base)


def _sample_rendered_message() -> RenderedEmailMessage:
    return RenderedEmailMessage(
        template_key="trust_invitation",
        template_version="v1",
        to_email="recipient@example.com",
        subject="Example",
        text_body="Plain text fallback",
        html_body="<p>HTML body</p>",
    )


@pytest.mark.asyncio
async def test_brevo_provider_sends_message_and_captures_provider_message_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://api.brevo.com/v3/smtp/email")
        assert request.headers["api-key"] == "brevo-secret"
        payload = request.read().decode("utf-8")
        assert "recipient@example.com" in payload
        assert "Plain text fallback" in payload
        return httpx.Response(201, json={"messageId": "brevo-message-id"})

    provider = BrevoEmailProvider(
        _brevo_settings(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = await provider.send(_sample_rendered_message())

    assert result.provider == "brevo"
    assert result.status == "sent"
    assert result.provider_message_id == "brevo-message-id"


@pytest.mark.asyncio
async def test_brevo_provider_normalizes_4xx_failures(caplog: pytest.LogCaptureFixture) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"code": "invalid_parameter", "message": "bad recipient"},
        )

    provider = BrevoEmailProvider(
        _brevo_settings(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ServiceUnavailableError, match="Unable to send email"):
            await provider.send(_sample_rendered_message())

    assert "brevo_send_failed" in caplog.messages
    assert "brevo-secret" not in " ".join(record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_brevo_provider_normalizes_5xx_failures(caplog: pytest.LogCaptureFixture) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={"code": "service_unavailable", "message": "temporary outage"},
        )

    provider = BrevoEmailProvider(
        _brevo_settings(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ServiceUnavailableError, match="Unable to send email"):
            await provider.send(_sample_rendered_message())

    assert "brevo_send_failed" in caplog.messages


@pytest.mark.asyncio
async def test_brevo_provider_normalizes_timeout_failures(caplog: pytest.LogCaptureFixture) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    provider = BrevoEmailProvider(
        _brevo_settings(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ServiceUnavailableError, match="Unable to send email"):
            await provider.send(_sample_rendered_message())

    assert "brevo_send_timeout" in caplog.messages


@pytest.mark.asyncio
async def test_brevo_provider_sets_sender_reply_to_and_destination() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://api.brevo.com/v3/smtp/email")
        payload = request.read().decode("utf-8")
        assert "\"sender\":{\"email\":\"verify@kairoid.com\",\"name\":\"Kairo\"}" in payload
        assert "\"replyTo\":{\"email\":\"visitor@example.com\"}" in payload
        assert "\"to\":[{\"email\":\"contact@kairoid.com\"}]" in payload
        return httpx.Response(201, json={"messageId": "<brevo-message-id>"})

    provider = BrevoEmailProvider(
        _brevo_settings(
            email_from="verify@kairoid.com",
            email_reply_to="verify@kairoid.com",
        ),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = await provider.send(
        RenderedEmailMessage(
            template_key="contact_form_submission",
            template_version="v1",
            to_email="contact@kairoid.com",
            subject="New contact request — Kairo",
            text_body="Plain text fallback",
            html_body="<p>HTML body</p>",
            reply_to="visitor@example.com",
        )
    )

    assert result.provider == "brevo"
    assert result.status == "sent"
    assert result.provider_message_id == "<brevo-message-id>"
