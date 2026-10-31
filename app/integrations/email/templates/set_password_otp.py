"""First-password verification email."""

from __future__ import annotations

from dataclasses import dataclass

from app.integrations.email.templates.base import (
    TransactionalEmailContent,
    html_escape,
    render_html,
    with_text_footer,
)


@dataclass(frozen=True, slots=True)
class SetPasswordOtpContext:
    code: str
    ttl_minutes: int
    first_name: str | None = None


def render_set_password_otp(context: SetPasswordOtpContext) -> TransactionalEmailContent:
    title = "Your KairoID verification code"
    safe_code = html_escape(context.code)
    safe_greeting = html_escape(context.first_name) if context.first_name else "there"
    preheader = (
        f"Use this code to set your KairoID password. "
        f"It expires in {context.ttl_minutes} minutes."
    )
    html_body = render_html(
        title=title,
        preheader=preheader,
        content=(
            f'<p style="margin:0 0 18px;font-size:16px;line-height:1.6;color:#263b4f;">'
            f"Hi {safe_greeting},</p>"
            '<p style="margin:0 0 12px;font-size:15px;line-height:1.65;color:#344b5f;">'
            "You requested to set a password for your KairoID account.</p>"
            '<p style="margin:0 0 18px;font-size:15px;line-height:1.65;color:#344b5f;">'
            "Use the verification code below to continue:</p>"
            f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:20px 0 22px;"><tr><td align="center" style="padding:22px 16px;background:#eaf8f7;border:1px solid #bfe7e4;border-radius:12px;font-size:32px;font-weight:800;letter-spacing:.2em;color:#075f5e;">{safe_code}</td></tr></table>'
            f'<p style="margin:0 0 18px;font-size:14px;line-height:1.6;color:#5d6f71;">'
            f"This code expires in {context.ttl_minutes} minutes.</p>"
            '<p style="margin:0 0 18px;font-size:14px;line-height:1.65;color:#5d6f71;">'
            "For your security, never share this code with anyone. KairoID will never ask "
            "you to provide this verification code by email, phone, or chat.</p>"
            '<p style="margin:0 0 20px;font-size:14px;line-height:1.65;color:#5d6f71;">'
            "If you didn't request this, you can safely ignore this email.</p>"
        ),
    )
    text_body = with_text_footer(
        f"Hi {context.first_name or 'there'},\n\n"
        "You requested to set a password for your KairoID account.\n\n"
        "Use the verification code below to continue:\n\n"
        f"Verification code: {context.code}\n\n"
        f"This code expires in {context.ttl_minutes} minutes.\n\n"
        "For your security, never share this code with anyone. KairoID will never ask "
        "you to provide this verification code by email, phone, or chat.\n\n"
        "If you didn't request this, you can safely ignore this email."
    )
    return TransactionalEmailContent(
        subject="Your KairoID verification code",
        html_body=html_body,
        text_body=text_body,
    )
