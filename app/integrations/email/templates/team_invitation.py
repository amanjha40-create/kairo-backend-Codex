"""Organization workspace team invitation email."""

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
class TeamInvitationContext:
    organization_name: str
    inviter_name: str
    invited_role_label: str
    invitation_url: str
    expires_at_iso: str
    invitee_name: str | None = None
    personal_message: str | None = None


def render_team_invitation(context: TeamInvitationContext) -> TransactionalEmailContent:
    title = f"Join {context.organization_name} on Kairo"
    safe_org = html_escape(context.organization_name)
    safe_inviter = html_escape(context.inviter_name)
    safe_role = html_escape(context.invited_role_label)
    safe_expiry = html_escape(context.expires_at_iso)
    greeting = f"Hello {html_escape(context.invitee_name)}," if context.invitee_name else "Hello,"
    message = (
        '<p style="margin:0 0 16px;font-size:14px;line-height:1.6;color:#5d6966;">'
        f"{html_escape(context.personal_message)}</p>"
        if context.personal_message
        else ""
    )
    greeting_text = f"Hello {context.invitee_name},\n\n" if context.invitee_name else ""
    message_text = f"{context.personal_message}\n\n" if context.personal_message else ""
    html_body = render_html(
        title=title,
        content=(
            '<p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#34413e;">'
            f"{greeting}</p>"
            f'<p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#34413e;">'
            f"{safe_inviter} invited you to join <strong>{safe_org}</strong> as "
            f"<strong>{safe_role}</strong>.</p>"
            f"{message}"
            f"{action_link(label='Accept team invitation', url=context.invitation_url)}"
            f'<p style="margin:0 0 12px;font-size:14px;line-height:1.6;color:#5d6966;">'
            f"This invitation expires at {safe_expiry} and can only be used once.</p>"
            '<p style="margin:0 0 20px;font-size:13px;line-height:1.6;color:#697572;">'
            "If you did not expect this invitation, do not use or forward the link.</p>"
        ),
    )
    text_body = with_text_footer(
        f"{greeting_text}"
        f"{context.inviter_name} invited you to join {context.organization_name} on Kairo "
        f"as {context.invited_role_label}.\n\n"
        f"{message_text}"
        f"Accept team invitation: {context.invitation_url}\n\n"
        f"This invitation expires at {context.expires_at_iso} and can only be used once.\n\n"
        "If you did not expect this invitation, do not use or forward the link."
    )
    return TransactionalEmailContent(
        subject=f"Kairo — join {context.organization_name}",
        html_body=html_body,
        text_body=text_body,
    )
