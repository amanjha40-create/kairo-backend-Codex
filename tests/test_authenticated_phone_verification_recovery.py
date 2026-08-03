"""Focused service coverage for authenticated Candidate phone recovery."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.auth.service import AuthService
from app.exceptions import ConflictError, RateLimitError, UnauthorizedError
from app.schemas.auth import (
    AuthenticatedPhoneVerificationSendRequest,
    AuthenticatedPhoneVerificationVerifyRequest,
)
from tests.test_staging_phone_otp import FIXED_CODE, _settings


class _RecoveryOtpStore:
    def __init__(self, *, verifies: bool = True, resend_allowed: bool = True) -> None:
        self.verifies = verifies
        self.resend_allowed = resend_allowed
        self.stored: tuple[UUID, str, str] | None = None
        self.failed_attempts: list[tuple[UUID, str]] = []
        self.cooldowns: list[tuple[UUID, str]] = []

    async def enforce_send_rate(self, *_: object) -> None:
        return None

    async def store_otp(self, subject_id: UUID, channel: str, code: str) -> None:
        self.stored = (subject_id, channel, code)

    async def verify_and_consume(self, *_: object) -> bool:
        return self.verifies

    async def assert_redis_resend_allowed(self, subject_id: UUID, channel: str) -> None:
        if not self.resend_allowed:
            raise RateLimitError(
                "Please wait before requesting another code.",
                retry_after_seconds=30,
            )

    async def mark_redis_resend_cooldown(self, subject_id: UUID, channel: str) -> None:
        self.cooldowns.append((subject_id, channel))

    async def record_failed_verification_attempt(self, subject_id: UUID, channel: str) -> None:
        self.failed_attempts.append((subject_id, channel))

    async def clear_verification_attempts(self, *_: object) -> None:
        return None


class _Users:
    def __init__(self, user) -> None:  # noqa: ANN001
        self.user = user

    async def get_by_id(self, user_id: UUID):  # noqa: ANN201
        return self.user if self.user.id == user_id else None

    async def get_by_phone(self, phone: str):  # noqa: ANN201
        return self.user if self.user.phone == phone else None


class _Session:
    async def commit(self) -> None:
        return None


class _PhoneSender:
    def challenge_code(self, *, to_phone: str, generated_code: str) -> str:
        del to_phone, generated_code
        return FIXED_CODE

    async def send_signup_otp(self, *, to_phone: str, code: str, ttl_minutes: int) -> None:
        del to_phone, code, ttl_minutes


def _user(phone: str | None = "+919876543210") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        phone=phone,
        phone_verified_at=None,
        email_verified_at=datetime.now(tz=UTC),
        is_active=True,
    )


def _service(user, otp: _RecoveryOtpStore) -> AuthService:  # noqa: ANN001
    service = object.__new__(AuthService)
    service._settings = _settings()  # noqa: SLF001
    service._users = _Users(user)  # type: ignore[assignment]  # noqa: SLF001
    service._otp = otp  # type: ignore[assignment]  # noqa: SLF001
    service._phone = _PhoneSender()  # type: ignore[assignment]  # noqa: SLF001
    service._session = _Session()  # type: ignore[assignment]  # noqa: SLF001
    return service


@pytest.mark.asyncio
async def test_authenticated_phone_send_binds_otp_to_current_user_with_missing_phone() -> None:
    user = _user(phone=None)
    otp = _RecoveryOtpStore()

    response = await _service(user, otp).send_authenticated_phone_verification(
        user.id,
        AuthenticatedPhoneVerificationSendRequest(phone="9876543210"),
    )

    assert user.phone == "+919876543210"
    assert otp.stored == (user.id, "authenticated_phone", FIXED_CODE)
    assert response.phone_masked == "+91******3210"
    assert response.phone_verified is False


@pytest.mark.asyncio
async def test_authenticated_phone_resend_respects_cooldown() -> None:
    user = _user()
    with pytest.raises(RateLimitError):
        await _service(
            user,
            _RecoveryOtpStore(resend_allowed=False),
        ).resend_authenticated_phone_verification(user.id)


@pytest.mark.asyncio
async def test_authenticated_phone_verify_marks_only_current_user_verified() -> None:
    user = _user()
    otp = _RecoveryOtpStore()

    response = await _service(user, otp).verify_authenticated_phone_verification(
        user.id,
        AuthenticatedPhoneVerificationVerifyRequest(code=FIXED_CODE),
    )

    assert user.phone_verified_at is not None
    assert response.phone_verified is True


@pytest.mark.asyncio
async def test_authenticated_phone_invalid_or_cross_user_verification_is_rejected() -> None:
    user = _user()
    otp = _RecoveryOtpStore(verifies=False)
    service = _service(user, otp)

    with pytest.raises(UnauthorizedError, match="Invalid or expired"):
        await service.verify_authenticated_phone_verification(
            user.id,
            AuthenticatedPhoneVerificationVerifyRequest(code="000000"),
        )
    assert otp.failed_attempts == [(user.id, "authenticated_phone")]

    with pytest.raises(UnauthorizedError):
        await service.verify_authenticated_phone_verification(
            uuid4(),
            AuthenticatedPhoneVerificationVerifyRequest(code=FIXED_CODE),
        )


@pytest.mark.asyncio
async def test_authenticated_phone_requires_a_number_when_the_account_has_none() -> None:
    user = _user(phone=None)
    with pytest.raises(ConflictError, match="mobile number is required"):
        await _service(user, _RecoveryOtpStore()).send_authenticated_phone_verification(
            user.id,
            AuthenticatedPhoneVerificationSendRequest(),
        )
