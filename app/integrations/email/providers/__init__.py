"""Email provider implementations and factory."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.integrations.email.providers.base import EmailProvider
from app.integrations.email.providers.console import ConsoleEmailProvider
from app.integrations.email.providers.smtp_provider import SmtpEmailProvider


def get_email_provider(settings: Settings | None = None) -> EmailProvider:
    resolved = settings or get_settings()
    if resolved.email_backend == "smtp":
        return SmtpEmailProvider(resolved)
    return ConsoleEmailProvider(resolved)


__all__ = [
    "ConsoleEmailProvider",
    "EmailProvider",
    "SmtpEmailProvider",
    "get_email_provider",
]
