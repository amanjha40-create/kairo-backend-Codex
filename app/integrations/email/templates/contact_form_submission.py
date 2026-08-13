"""Internal notification email for public website contact-form submissions."""

from __future__ import annotations

from dataclasses import dataclass

from app.integrations.email.templates.base import (
    TransactionalEmailContent,
    html_escape,
    render_html,
    with_text_footer,
)


@dataclass(frozen=True, slots=True)
class ContactFormSubmissionContext:
    full_name: str
    work_email: str
    company: str
    hires_per_month: str
    message: str
    submitted_at_iso: str
    request_id: str


def _html_row(label: str, value: str, *, top_align: bool = False) -> str:
    label_cell = (
        '<td style="padding:8px 0;font-weight:600;color:#17211f;'
        f'{"vertical-align:top;" if top_align else ""}">{html_escape(label)}</td>'
    )
    value_cell = (
        '<td style="padding:8px 0;color:#33403d;white-space:normal;">'
        f"{value}</td>"
    )
    return f"<tr>{label_cell}{value_cell}</tr>"


def render_contact_form_submission(
    context: ContactFormSubmissionContext,
) -> TransactionalEmailContent:
    subject = f"New contact request — {context.company}"
    safe_message = "<br />".join(
        html_escape(line) for line in context.message.splitlines() or [""]
    )
    rows = [
        _html_row("Full name", html_escape(context.full_name)),
        _html_row("Work email", html_escape(context.work_email)),
        _html_row("Company", html_escape(context.company)),
        _html_row("Hires per month", html_escape(context.hires_per_month)),
        _html_row("Message", safe_message, top_align=True),
        _html_row("Submitted at", html_escape(context.submitted_at_iso)),
        _html_row("Request ID", html_escape(context.request_id)),
    ]
    html_body = render_html(
        title="New contact request",
        content=(
            "<p style=\"margin:0 0 16px;font-size:15px;line-height:1.7;color:#33403d;\">"
            "A new message was submitted through the public Kairo website contact form."
            "</p>"
            "<table role=\"presentation\" cellspacing=\"0\" cellpadding=\"0\" "
            "style=\"width:100%;border-collapse:collapse;\">"
            f"{''.join(rows)}"
            "</table>"
        ),
    )
    text_body = with_text_footer(
        "\n".join(
            [
                "New contact request",
                "",
                f"Full name: {context.full_name}",
                f"Work email: {context.work_email}",
                f"Company: {context.company}",
                f"Hires per month: {context.hires_per_month}",
                "Message:",
                context.message,
                "",
                f"Submitted at: {context.submitted_at_iso}",
                f"Request ID: {context.request_id}",
            ]
        )
    )
    return TransactionalEmailContent(
        subject=subject,
        html_body=html_body,
        text_body=text_body,
    )
