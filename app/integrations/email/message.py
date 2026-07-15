"""Convert rendered transactional content into transport-ready MIME messages."""

from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime, make_msgid, parseaddr

from app.integrations.email.templates.base import TransactionalEmailContent


def build_mime_message(
    *,
    content: TransactionalEmailContent,
    to_email: str,
    from_email: str,
    reply_to: str | None = None,
) -> EmailMessage:
    _validate_header_value("subject", content.subject)
    _validate_address("to_email", to_email)
    _validate_address("from_email", from_email)
    if reply_to:
        _validate_address("reply_to", reply_to)

    message = EmailMessage(policy=SMTP)
    message["Subject"] = content.subject
    message["From"] = from_email
    message["To"] = to_email
    if reply_to:
        message["Reply-To"] = reply_to
    message["Date"] = format_datetime(datetime.now(timezone.utc))
    message["Message-ID"] = make_msgid()
    message["MIME-Version"] = "1.0"
    message.set_content(content.text_body)
    if content.html_body:
        message.add_alternative(content.html_body, subtype="html")
    return message


def _validate_header_value(name: str, value: str) -> None:
    if "\r" in value or "\n" in value:
        raise ValueError(f"Invalid newline in email {name}")


def _validate_address(name: str, value: str) -> None:
    _validate_header_value(name, value)
    normalized = value.strip()
    display_name, address = parseaddr(normalized)
    if display_name or address != normalized or address.count("@") != 1:
        raise ValueError(f"Invalid email address for {name}")
