"""Employer verification request template."""

from __future__ import annotations

from dataclasses import dataclass

from app.integrations.email.templates.base import (
    TransactionalEmailContent,
    action_link,
    html_escape,
    render_html,
    with_text_footer,
)


@dataclass(frozen=True, slots=True)
class EmployerVerificationContext:
    contact_name: str
    subject_full_name: str
    employer_name: str
    job_title: str
    relationship: str
    review_url: str
    expires_hours: int


def render_employer_verification(
    context: EmployerVerificationContext,
) -> TransactionalEmailContent:
    title = "Employment verification request"
    safe_contact = html_escape(context.contact_name)
    safe_subject = html_escape(context.subject_full_name)
    safe_employer = html_escape(context.employer_name)
    safe_title = html_escape(context.job_title)
    safe_relationship = html_escape(context.relationship)
    safe_url = html_escape(context.review_url)
    html_body = render_html(
        title=title,
        content=(
            f'<p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#34413e;">Hello <strong>{safe_contact}</strong>,</p>'
            f'<p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#34413e;">'
            f"<strong>{safe_subject}</strong> has asked you to verify their employment as "
            f"<strong>{safe_title}</strong> at <strong>{safe_employer}</strong>.</p>"
            f'<p style="margin:0 0 16px;font-size:14px;line-height:1.6;color:#5d6966;">'
            f"Your relationship: {safe_relationship}</p>"
            f"{action_link(label='Review and respond', url=context.review_url)}"
            f'<p style="margin:0 0 8px;font-size:13px;line-height:1.5;color:#697572;">'
            f"This secure link expires in {context.expires_hours} hours. "
            "Do not forward or share it.</p>"
            f'<p style="margin:0 0 16px;font-size:12px;line-height:1.5;word-break:break-all;color:#697572;">{safe_url}</p>'
            '<p style="margin:0 0 20px;font-size:13px;line-height:1.6;color:#697572;">'
            "If you did not expect this request, do not open the link and contact Kairo support.</p>"
        ),
    )
    text_body = with_text_footer(
        f"Hello {context.contact_name},\n\n"
        f"{context.subject_full_name} has asked you to verify their employment as "
        f"{context.job_title} at {context.employer_name}.\n"
        f"Your relationship: {context.relationship}.\n\n"
        f"Review and respond: {context.review_url}\n\n"
        f"This secure link expires in {context.expires_hours} hours. Do not forward or share it.\n\n"
        "If you did not expect this request, do not open the link and contact Kairo support."
    )
    return TransactionalEmailContent(
        subject="Kairo — employment verification request",
        html_body=html_body,
        text_body=text_body,
    )
