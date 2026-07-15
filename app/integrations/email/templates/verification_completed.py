"""Verification completed notification template."""

from __future__ import annotations

from dataclasses import dataclass

from app.integrations.email.templates.base import (
    TransactionalEmailContent,
    html_escape,
    render_html,
    with_text_footer,
)


@dataclass(frozen=True, slots=True)
class VerificationCompletedContext:
    subject_name: str
    organization_name: str
    request_type: str
    completed_at_iso: str


def render_verification_completed(
    context: VerificationCompletedContext,
) -> TransactionalEmailContent:
    request_type = context.request_type.replace("_", " ").strip().title()
    title = f"{request_type} verification complete"
    safe_subject = html_escape(context.subject_name)
    safe_organization = html_escape(context.organization_name)
    safe_request_type = html_escape(request_type.lower())
    safe_completed_at = html_escape(context.completed_at_iso)
    html_body = render_html(
        title=title,
        content=(
            f'<p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#34413e;">Hello <strong>{safe_subject}</strong>,</p>'
            f'<p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#34413e;">'
            f"Your {safe_request_type} verification with <strong>{safe_organization}</strong> "
            "has been completed on Kairo.</p>"
            f'<p style="margin:0 0 20px;font-size:13px;line-height:1.6;color:#697572;">'
            f"Completed at: {safe_completed_at}</p>"
        ),
    )
    text_body = with_text_footer(
        f"Hello {context.subject_name},\n\n"
        f"Your {request_type.lower()} verification with {context.organization_name} "
        "has been completed on Kairo.\n\n"
        f"Completed at: {context.completed_at_iso}"
    )
    return TransactionalEmailContent(
        subject=f"Your {request_type} verification is complete",
        html_body=html_body,
        text_body=text_body,
    )
