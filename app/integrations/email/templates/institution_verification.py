"""Institution verification request template."""

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
class InstitutionVerificationContext:
    contact_name: str
    subject_name: str
    institution_name: str
    degree: str
    programme: str
    review_url: str
    expires_hours: int


def render_institution_verification(
    context: InstitutionVerificationContext,
) -> TransactionalEmailContent:
    title = "Education verification request"
    safe_contact = html_escape(context.contact_name)
    safe_subject = html_escape(context.subject_name)
    safe_institution = html_escape(context.institution_name)
    safe_degree = html_escape(context.degree)
    safe_programme = html_escape(context.programme)
    safe_url = html_escape(context.review_url)
    html_body = render_html(
        title=title,
        content=(
            (
                f'<p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#34413e;">'
                f"Hello <strong>{safe_contact}</strong>,</p>"
            )
            + (
                f'<p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#34413e;">'
                f"Kairo has asked your institution to review an education claim for "
                f"<strong>{safe_subject}</strong>.</p>"
            )
            + (
                f'<p style="margin:0 0 16px;font-size:14px;line-height:1.6;color:#5d6966;">'
                f"Institution: <strong>{safe_institution}</strong><br/>"
                f"Degree: <strong>{safe_degree}</strong><br/>"
                f"Programme: <strong>{safe_programme}</strong></p>"
            )
            + f"{action_link(label='Review and respond', url=context.review_url)}"
            + (
                f'<p style="margin:0 0 8px;font-size:13px;line-height:1.5;color:#697572;">'
                f"This secure link expires in {context.expires_hours} hours. "
                "Do not forward or share it.</p>"
            )
            + (
                f'<p style="margin:0 0 16px;font-size:12px;line-height:1.5;'
                f'word-break:break-all;color:#697572;">{safe_url}</p>'
            )
            + (
                '<p style="margin:0 0 20px;font-size:13px;line-height:1.6;color:#697572;">'
                "If you did not expect this request, do not open the link and contact "
                "Kairo support.</p>"
            )
        ),
    )
    text_body = with_text_footer(
        f"Hello {context.contact_name},\n\n"
        f"Kairo has asked your institution to review an education claim for "
        f"{context.subject_name}.\n"
        f"Institution: {context.institution_name}\n"
        f"Degree: {context.degree}\n"
        f"Programme: {context.programme}\n\n"
        f"Review and respond: {context.review_url}\n\n"
        f"This secure link expires in {context.expires_hours} hours. "
        "Do not forward or share it.\n\n"
        "If you did not expect this request, do not open the link and contact Kairo support."
    )
    return TransactionalEmailContent(
        subject="Kairo — education verification request",
        html_body=html_body,
        text_body=text_body,
    )
