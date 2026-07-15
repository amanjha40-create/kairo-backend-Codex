"""Convert rendered transactional content into transport-ready MIME messages."""

from __future__ import annotations

from email.message import EmailMessage

from app.integrations.email.templates.base import TransactionalEmailContent


def build_mime_message(
    *,
    content: TransactionalEmailContent,
    to_email: str,
    from_email: str,
    reply_to: str | None = None,
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = content.subject
    message["From"] = from_email
    message["To"] = to_email
    if reply_to:
        message["Reply-To"] = reply_to
    message.set_content(content.text_body)
    message.add_alternative(content.html_body, subtype="html")
    return message
