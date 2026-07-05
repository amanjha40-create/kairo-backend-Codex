"""SMTP email message builder tests."""

from __future__ import annotations

from app.integrations.email.smtp import build_signup_otp_email


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
    assert "123456" in msg.get_content()
