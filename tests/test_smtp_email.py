"""SMTP email message builder tests."""

from __future__ import annotations

from app.integrations.email.smtp import build_password_reset_email, build_signup_otp_email


def _bodies(message) -> tuple[str, str]:
    plain = message.get_body(preferencelist=("plain",))
    html = message.get_body(preferencelist=("html",))
    assert plain is not None
    assert html is not None
    return plain.get_content(), html.get_content()


def test_build_signup_otp_email() -> None:
    msg = build_signup_otp_email(
        app_name="Kairo",
        to_email="user@example.com",
        from_email="noreply@kairo.app",
        code="123456",
        ttl_minutes=10,
    )
    assert msg["To"] == "user@example.com"
    assert msg["From"] == "noreply@kairo.app"
    text_body, html_body = _bodies(msg)
    assert "123456" in text_body
    assert "123456" in html_body


def test_build_password_reset_email() -> None:
    msg = build_password_reset_email(
        app_name="Kairo",
        to_email="user@example.com",
        from_email="noreply@kairo.app",
        reset_token="reset-token-123",
        ttl_minutes=30,
    )
    assert msg["To"] == "user@example.com"
    assert msg["From"] == "noreply@kairo.app"
    text_body, html_body = _bodies(msg)
    assert "reset-token-123" in text_body
    assert "reset-token-123" in html_body
