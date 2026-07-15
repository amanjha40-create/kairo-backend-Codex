"""Trust invitation template."""

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
class TrustInvitationContext:
    organization_name: str
    subject_name: str
    invitation_url: str
    expires_at_iso: str


def render_trust_invitation(context: TrustInvitationContext) -> TransactionalEmailContent:
    title = "Trust invitation"
    safe_subject = html_escape(context.subject_name)
    safe_organization = html_escape(context.organization_name)
    safe_expiry = html_escape(context.expires_at_iso)
    safe_url = html_escape(context.invitation_url)
    html_body = render_html(
        title=title,
        content=(
            f'<p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#34413e;">Hello <strong>{safe_subject}</strong>,</p>'
            f'<p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#34413e;">'
            f"<strong>{safe_organization}</strong> invited you to continue a trust verification workflow on Kairo.</p>"
            f"{action_link(label='Open invitation', url=context.invitation_url)}"
            f'<p style="margin:0 0 8px;font-size:13px;line-height:1.5;color:#697572;">'
            f"This secure invitation expires at {safe_expiry}. Do not forward or share it.</p>"
            f'<p style="margin:0 0 16px;font-size:12px;line-height:1.5;word-break:break-all;color:#697572;">{safe_url}</p>'
            '<p style="margin:0 0 20px;font-size:13px;line-height:1.6;color:#697572;">'
            "If you did not expect this invitation, do not open the link and contact Kairo support.</p>"
        ),
    )
    text_body = with_text_footer(
        f"Hello {context.subject_name},\n\n"
        f"{context.organization_name} invited you to continue a trust verification workflow on Kairo.\n\n"
        f"Open your invitation: {context.invitation_url}\n\n"
        f"This secure invitation expires at {context.expires_at_iso}. Do not forward or share it.\n\n"
        "If you did not expect this invitation, do not open the link and contact Kairo support."
    )
    return TransactionalEmailContent(
        subject=f"{context.organization_name} invited you to Kairo",
        html_body=html_body,
        text_body=text_body,
    )
