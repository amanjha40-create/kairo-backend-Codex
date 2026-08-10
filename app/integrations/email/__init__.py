"""Outbound email integrations."""

from app.integrations.email.providers import (
    BrevoEmailProvider,
    ConsoleEmailProvider,
    EmailProvider,
    SesEmailProvider,
    SmtpEmailProvider,
    get_email_provider,
)
from app.integrations.email.renderer import EmailTemplateRenderer
from app.integrations.email.sender import (
    ConsoleEmailSender,
    EmailSender,
    ProviderEmailSender,
    get_email_sender,
)
from app.integrations.email.smtp import SmtpEmailSender

__all__ = [
    "BrevoEmailProvider",
    "ConsoleEmailProvider",
    "ConsoleEmailSender",
    "EmailProvider",
    "EmailSender",
    "EmailTemplateRenderer",
    "ProviderEmailSender",
    "SmtpEmailProvider",
    "SesEmailProvider",
    "SmtpEmailSender",
    "get_email_provider",
    "get_email_sender",
]
