"""HTML + plain-text employer verification emails with confirm / decline links."""

from __future__ import annotations

from email.message import EmailMessage

from app.integrations.email.message import build_mime_message
from app.integrations.email.templates.employer_verification import (
    EmployerVerificationContext,
    render_employer_verification,
)


def build_employer_verification_email(
    *,
    app_name: str,
    to_email: str,
    from_email: str,
    contact_name: str,
    subject_full_name: str,
    employer_name: str,
    job_title: str,
    relationship: str,
    review_url: str,
    expires_hours: int,
    reply_to: str | None = None,
) -> EmailMessage:
    """Compatibility wrapper around the canonical employer template."""

    del app_name
    content = render_employer_verification(
        EmployerVerificationContext(
            contact_name=contact_name,
            subject_full_name=subject_full_name,
            employer_name=employer_name,
            job_title=job_title,
            relationship=relationship,
            review_url=review_url,
            expires_hours=expires_hours,
        )
    )
    return build_mime_message(
        content=content,
        to_email=to_email,
        from_email=from_email,
        reply_to=reply_to,
    )
