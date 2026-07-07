"""Unit tests for email providers."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.integrations.email.providers import get_email_provider
from app.integrations.email.providers.console import ConsoleEmailProvider
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
