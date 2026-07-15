"""Outbound email integrations."""

from app.integrations.email.renderer import EmailTemplateRenderer
from app.integrations.email.providers import (
    ConsoleEmailProvider,
    EmailProvider,
    SmtpEmailProvider,
    SesEmailProvider,
    get_email_provider,
)
from app.integrations.email.sender import ConsoleEmailSender, EmailSender, get_email_sender
from app.integrations.email.smtp import SmtpEmailSender

__all__ = [
    "ConsoleEmailProvider",
    "ConsoleEmailSender",
    "EmailProvider",
    "EmailSender",
    "EmailTemplateRenderer",
    "SmtpEmailProvider",
    "SesEmailProvider",
    "SmtpEmailSender",
    "get_email_provider",
    "get_email_sender",
]
