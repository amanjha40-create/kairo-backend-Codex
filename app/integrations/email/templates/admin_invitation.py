"""Admin invitation email template."""

from __future__ import annotations

from dataclasses import dataclass

from app.integrations.email.templates.base import (
    TransactionalEmailContent,
    html_escape,
    render_html,
    with_text_footer,
)


@dataclass(frozen=True, slots=True)
class AdminInvitationContext:
    invited_role_label: str
    invitation_token: str
    expires_at_iso: str


def render_admin_invitation(context: AdminInvitationContext) -> TransactionalEmailContent:
    title = "You've been invited to Kairo Admin"
    safe_token = html_escape(context.invitation_token)
    safe_role = html_escape(context.invited_role_label)
    safe_expiry = html_escape(context.expires_at_iso)
    html_body = render_html(
        title=title,
        content=(
            '<p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#34413e;">'
            "A Kairo administrator has invited this email address to access the internal Admin Portal.</p>"
            f'<p style="margin:0 0 12px;font-size:14px;line-height:1.6;color:#5d6966;">'
            f"Sanctioned role: <strong>{safe_role}</strong></p>"
            f'<p style="margin:20px 0;padding:16px;background:#eef6f4;border-radius:10px;'
            f'font-size:15px;line-height:1.5;word-break:break-all;color:#174f4a;">{safe_token}</p>'
            f'<p style="margin:0 0 12px;font-size:14px;line-height:1.6;color:#5d6966;">'
            f"This invitation expires at {safe_expiry} and can only be accepted once.</p>"
            '<p style="margin:0 0 20px;font-size:13px;line-height:1.6;color:#697572;">'
            "Use this token only with the approved Kairo admin-invitation acceptance flow. "
            "Never forward or share it.</p>"
        ),
    )
    text_body = with_text_footer(
        "A Kairo administrator has invited this email address to access the internal Admin Portal.\n\n"
        f"Sanctioned role: {context.invited_role_label}\n\n"
        f"Admin invitation token: {context.invitation_token}\n\n"
        f"This invitation expires at {context.expires_at_iso} and can only be accepted once.\n\n"
        "Use this token only with the approved Kairo admin-invitation acceptance flow. Never share it."
    )
    return TransactionalEmailContent(
        subject="Kairo — admin access invitation",
        html_body=html_body,
        text_body=text_body,
    )
