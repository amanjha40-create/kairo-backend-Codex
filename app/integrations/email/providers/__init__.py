"""Email provider implementations and factory."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.config import Settings, get_settings
from app.integrations.email.providers.base import EmailProvider

if TYPE_CHECKING:
    from app.integrations.email.providers.brevo_provider import BrevoEmailProvider
    from app.integrations.email.providers.console import ConsoleEmailProvider
    from app.integrations.email.providers.ses_provider import SesEmailProvider
    from app.integrations.email.providers.smtp_provider import SmtpEmailProvider


def get_email_provider(settings: Settings | None = None) -> EmailProvider:
    resolved = settings or get_settings()
    if resolved.email_backend == "smtp":
        from app.integrations.email.providers.smtp_provider import SmtpEmailProvider

        return SmtpEmailProvider(resolved)
    if resolved.email_backend == "ses":
        from app.integrations.email.providers.ses_provider import SesEmailProvider

        return SesEmailProvider(resolved)
    if resolved.email_backend == "brevo":
        from app.integrations.email.providers.brevo_provider import BrevoEmailProvider

        return BrevoEmailProvider(resolved)
    if resolved.email_backend == "console":
        from app.integrations.email.providers.console import ConsoleEmailProvider

        return ConsoleEmailProvider(resolved)
    msg = f"Unsupported email provider: {resolved.email_backend}"
    raise ValueError(msg)


def __getattr__(name: str) -> Any:
    if name == "BrevoEmailProvider":
        from app.integrations.email.providers.brevo_provider import BrevoEmailProvider

        return BrevoEmailProvider
    if name == "ConsoleEmailProvider":
        from app.integrations.email.providers.console import ConsoleEmailProvider

        return ConsoleEmailProvider
    if name == "SesEmailProvider":
        from app.integrations.email.providers.ses_provider import SesEmailProvider

        return SesEmailProvider
    if name == "SmtpEmailProvider":
        from app.integrations.email.providers.smtp_provider import SmtpEmailProvider

        return SmtpEmailProvider
    raise AttributeError(name)


__all__ = [
    "BrevoEmailProvider",
    "ConsoleEmailProvider",
    "EmailProvider",
    "SesEmailProvider",
    "SmtpEmailProvider",
    "get_email_provider",
]
