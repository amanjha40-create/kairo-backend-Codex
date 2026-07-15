"""Password reset template."""

from __future__ import annotations

from dataclasses import dataclass

from app.integrations.email.templates.base import (
    TransactionalEmailContent,
    html_escape,
    render_html,
    with_text_footer,
)


@dataclass(frozen=True, slots=True)
class PasswordResetContext:
    reset_token: str
    ttl_minutes: int


def render_password_reset(context: PasswordResetContext) -> TransactionalEmailContent:
    title = "Reset your password"
    safe_token = html_escape(context.reset_token)
    html_body = render_html(
        title=title,
        content=(
            '<p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#34413e;">'
            "We received a request to reset your Kairo password.</p>"
            f'<p style="margin:20px 0;padding:16px;background:#eef6f4;border-radius:10px;'
            f'font-size:15px;line-height:1.5;word-break:break-all;color:#174f4a;">{safe_token}</p>'
            f'<p style="margin:0 0 12px;font-size:14px;line-height:1.6;color:#5d6966;">'
            f"This token expires in {context.ttl_minutes} minutes and can only be used once.</p>"
            '<p style="margin:0 0 20px;font-size:13px;line-height:1.6;color:#697572;">'
            "Never share this token. Kairo will never ask you to provide it by email or phone. "
            "If you did not request a password reset, you can ignore this email.</p>"
        ),
    )
    text_body = with_text_footer(
        "We received a request to reset your Kairo password.\n\n"
        f"Password reset token: {context.reset_token}\n\n"
        f"This token expires in {context.ttl_minutes} minutes and can only be used once.\n\n"
        "Never share this token. Kairo will never ask you to provide it by email or phone. "
        "If you did not request a password reset, you can ignore this email."
    )
    return TransactionalEmailContent(
        subject="Kairo — reset your password",
        html_body=html_body,
        text_body=text_body,
    )
