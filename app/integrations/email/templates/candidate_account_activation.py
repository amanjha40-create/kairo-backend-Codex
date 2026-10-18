"""Candidate account claim email; the opaque credential is never part of audit metadata."""

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
class CandidateAccountActivationContext:
    candidate_name: str
    activation_url: str
    expires_at_iso: str


def render_candidate_account_activation(
    context: CandidateAccountActivationContext,
) -> TransactionalEmailContent:
    safe_name = html_escape(context.candidate_name)
    safe_expiry = html_escape(context.expires_at_iso)
    html_body = render_html(
        title="Claim your Kairo account",
        content=(
            f'<p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#34413e;">'
            f"Hello <strong>{safe_name}</strong>, a Kairo profile was prepared for you. "
            "Review it by claiming the account and choosing your own password.</p>"
            f"{action_link(label='Claim account', url=context.activation_url)}"
            f'<p style="margin:0 0 12px;font-size:14px;line-height:1.6;color:#5d6966;">'
            f"This single-use link expires at {safe_expiry}. Do not forward it.</p>"
            '<p style="margin:0 0 20px;font-size:13px;line-height:1.6;color:#697572;">'
            "If you did not expect this message, do not use the link and contact Kairo support.</p>"
        ),
    )
    text_body = with_text_footer(
        f"Hello {context.candidate_name},\n\n"
        "A Kairo profile was prepared for you. Claim the account and choose your own password:\n\n"
        f"{context.activation_url}\n\n"
        f"This single-use link expires at {context.expires_at_iso}. Do not forward it.\n\n"
        "If you did not expect this message, do not use the link and contact Kairo support."
    )
    return TransactionalEmailContent(
        subject="Kairo — claim your account",
        html_body=html_body,
        text_body=text_body,
    )
