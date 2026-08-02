"""Regression coverage for organization signup OTP start behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.auth.service import AuthService
from app.config import Settings
from app.schemas.auth import OrganizationSignupStartRequest


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        "jwt_secret_key": "test-jwt-secret-key-32-chars-minimum!!",
        "email_backend": "ses",
        "email_send_enabled": True,
        "aws_region": "us-east-1",
        "ses_from_email": "verify@kairoid.com",
    }
    values.update(overrides)
    return Settings(**values)


class _FakeUsers:
    async def get_by_email(self, _: str) -> None:
        return None


class _FakeOtpStore:
    def __init__(self) -> None:
        self.stored: tuple[UUID, str, str] | None = None

    async def enforce_send_rate(self, *_: object) -> None:
        return None

    async def store_otp(self, signup_session_id: UUID, channel: str, code: str) -> None:
        self.stored = (signup_session_id, channel, code)

    def seconds_until_resend_allowed(self, sent_at: object) -> int:
        return 30 if sent_at is not None else 0


class _FakeEmailSender:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def send_signup_otp(self, *, to_email: str, code: str, ttl_minutes: int) -> None:
        self.calls.append(
            {
                "to_email": to_email,
                "code": code,
                "ttl_minutes": ttl_minutes,
            }
        )


class _FakeSession:
    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


def _pending_signup() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        email="staff@example.com",
        phone=None,
        expires_at=datetime.now(tz=UTC) + timedelta(hours=24),
        email_verified_at=None,
        phone_verified_at=None,
        email_otp_sent_count=0,
        phone_otp_sent_count=0,
        email_verify_attempt_count=0,
        phone_verify_attempt_count=0,
        email_last_otp_sent_at=None,
        phone_last_otp_sent_at=None,
    )


@pytest.mark.asyncio
async def test_start_organization_signup_sends_initial_email_otp() -> None:
    pending = _pending_signup()
    otp_store = _FakeOtpStore()
    email_sender = _FakeEmailSender()

    service = object.__new__(AuthService)
    service._settings = _settings()  # noqa: SLF001
    service._users = _FakeUsers()  # type: ignore[assignment]  # noqa: SLF001
    service._otp = otp_store  # type: ignore[assignment]  # noqa: SLF001
    service._email = email_sender  # type: ignore[assignment]  # noqa: SLF001
    service._session = _FakeSession()  # type: ignore[assignment]  # noqa: SLF001

    async def fake_prepare_pending_signup(**kwargs: object) -> SimpleNamespace:
        assert kwargs["email"] == "staff@example.com"
        return pending

    service._get_or_prepare_pending_signup = fake_prepare_pending_signup  # type: ignore[method-assign]  # noqa: SLF001

    response = await service.start_organization_signup(
        OrganizationSignupStartRequest(
            full_name="Workspace Owner",
            work_email="staff@example.com",
            password="StrongPassword123!",
        )
    )

    assert otp_store.stored is not None
    assert otp_store.stored[:2] == (pending.id, "email")
    assert otp_store.stored[2].isdigit()
    assert len(otp_store.stored[2]) == 6

    assert email_sender.calls == [
        {
            "to_email": "staff@example.com",
            "code": otp_store.stored[2],
            "ttl_minutes": 10,
        }
    ]
    assert pending.email_otp_sent_count == 1
    assert pending.email_last_otp_sent_at is not None

    assert response.signup_session_id == pending.id
    assert response.email_verified is False
    assert response.email_resend_after_seconds == 30
