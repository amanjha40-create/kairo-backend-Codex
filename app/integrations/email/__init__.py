"""Outbound email integrations."""

from app.integrations.email.sender import ConsoleEmailSender, EmailSender, get_email_sender
from app.integrations.email.smtp import SmtpEmailSender

__all__ = ["ConsoleEmailSender", "EmailSender", "SmtpEmailSender", "get_email_sender"]
