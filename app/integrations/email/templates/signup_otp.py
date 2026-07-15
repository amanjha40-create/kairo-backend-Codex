"""Signup email OTP template."""

from __future__ import annotations

from dataclasses import dataclass

from app.integrations.email.templates.base import (
    TransactionalEmailContent,
    html_escape,
    render_html,
    with_text_footer,
)


@dataclass(frozen=True, slots=True)
class SignupOtpContext:
    code: str
    ttl_minutes: int


def render_signup_otp(context: SignupOtpContext) -> TransactionalEmailContent:
    title = "Verify your email"
    safe_code = html_escape(context.code)
    html_body = render_html(
        title=title,
        content=(
            '<p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#34413e;">'
            "Use this one-time code to continue creating your Kairo account.</p>"
            f'<p style="margin:20px 0;padding:18px;text-align:center;background:#eef6f4;'
            f'border-radius:10px;font-size:30px;font-weight:700;letter-spacing:.18em;color:#174f4a;">{safe_code}</p>'
            f'<p style="margin:0 0 12px;font-size:14px;line-height:1.6;color:#5d6966;">'
            f"This code expires in {context.ttl_minutes} minutes.</p>"
            '<p style="margin:0 0 20px;font-size:13px;line-height:1.6;color:#697572;">'
            "For your security, Kairo will never ask you to share this code. "
            "If you did not request it, you can ignore this email.</p>"
        ),
    )
    text_body = with_text_footer(
        "Use this one-time code to continue creating your Kairo account.\n\n"
        f"Verification code: {context.code}\n\n"
        f"This code expires in {context.ttl_minutes} minutes.\n\n"
        "For your security, Kairo will never ask you to share this code. "
        "If you did not request it, you can ignore this email."
    )
    return TransactionalEmailContent(
        subject="Kairo — verify your email",
        html_body=html_body,
        text_body=text_body,
    )
