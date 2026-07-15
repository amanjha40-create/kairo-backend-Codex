"""Security coverage for the staging-only fixed phone OTP provider."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.auth.service import AuthService
from app.auth.signup_otp import SignupOtpStore
from app.config import Settings
from app.exceptions import UnauthorizedError
from app.integrations.phone_otp.sender import StagingFixedPhoneOtpSender, get_phone_otp_sender
from app.main import app


FIXED_CODE = "246810"
ALLOWED_PHONE = "+919876543210"


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        "jwt_secret_key": "test-jwt-secret-key-32-chars-minimum!!",
        "app_env": "staging",
        "phone_otp_backend": "staging_fixed",
        "phone_otp_enabled": True,
        "staging_phone_otp_code": FIXED_CODE,
        "staging_phone_otp_allowed_numbers": [ALLOWED_PHONE],
    }
    values.update(overrides)
    return Settings(**values)


def test_staging_fixed_provider_requires_staging_environment() -> None:
    with pytest.raises(ValidationError, match="requires APP_ENV=staging"):
        _settings(app_env="development")


def test_staging_fixed_provider_is_forbidden_in_production() -> None:
    with pytest.raises(ValidationError, match="forbidden in APP_ENV=production"):
        _settings(
            app_env="production",
            jwt_secret_key="production-jwt-secret-key-that-is-longer-than-forty-eight-characters",
            email_backend="smtp",
            smtp_host="smtp.example.com",
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"staging_phone_otp_code": None}, "STAGING_PHONE_OTP_CODE"),
        ({"staging_phone_otp_code": "12345"}, "exactly six digits"),
        ({"staging_phone_otp_allowed_numbers": []}, "at least one E.164"),
        ({"staging_phone_otp_allowed_numbers": ["9876543210"]}, "normalized E.164"),
    ),
)
def test_staging_fixed_provider_validates_secret_and_allowlist(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _settings(**overrides)


def test_provider_factory_selects_staging_fixed() -> None:
    assert isinstance(get_phone_otp_sender(_settings()), StagingFixedPhoneOtpSender)


@pytest.mark.asyncio
async def test_allowed_number_uses_injected_code_without_logging_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sender = StagingFixedPhoneOtpSender(_settings())

    challenge = sender.challenge_code(to_phone=ALLOWED_PHONE, generated_code="111111")
    with caplog.at_level(logging.INFO):
        await sender.send_signup_otp(
            to_phone=ALLOWED_PHONE,
            code=challenge,
            ttl_minutes=10,
        )

    assert challenge == FIXED_CODE
    assert FIXED_CODE not in caplog.text
    assert ALLOWED_PHONE not in caplog.text


def test_unapproved_number_receives_indistinguishable_random_challenge() -> None:
    sender = StagingFixedPhoneOtpSender(_settings())

    challenge = sender.challenge_code(to_phone="+919999999999", generated_code="111111")

    assert challenge == "111111"
    assert challenge != FIXED_CODE


class _OtpRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, **_: object) -> None:
        self.values[key] = value

    async def eval(self, _: str, __: int, key: str, expected_hash: str) -> int:
        if self.values.get(key) != expected_hash:
            return 0
        del self.values[key]
        return 1

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.values.pop(key, None)


@pytest.mark.asyncio
async def test_fixed_challenge_remains_session_bound_expiring_and_single_use() -> None:
    redis = _OtpRedis()
    store = SignupOtpStore(redis, _settings())  # type: ignore[arg-type]
    active_session = uuid4()
    different_session = uuid4()

    await store.store_otp(active_session, "phone", FIXED_CODE)

    assert await store.verify_and_consume(different_session, "phone", FIXED_CODE) is False
    assert await store.verify_and_consume(active_session, "phone", "000000") is False
    assert await store.verify_and_consume(active_session, "phone", FIXED_CODE) is True
    assert await store.verify_and_consume(active_session, "phone", FIXED_CODE) is False

    await store.store_otp(active_session, "phone", FIXED_CODE)
    await store.clear(active_session, "phone")
    assert await store.verify_and_consume(active_session, "phone", FIXED_CODE) is False


class _FakeOtpStore:
    def __init__(self, *, verifies: bool = True) -> None:
        self.verifies = verifies
        self.stored: tuple[UUID, str, str] | None = None

    async def enforce_send_rate(self, *_: object) -> None:
        return None

    async def store_otp(self, signup_session_id: UUID, channel: str, code: str) -> None:
        self.stored = (signup_session_id, channel, code)

    async def verify_and_consume(self, *_: object) -> bool:
        return self.verifies

    def seconds_until_resend_allowed(self, _: object) -> int:
        return 0


class _FakeSession:
    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


def _pending(phone: str = ALLOWED_PHONE) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        email="tester@example.com",
        phone=phone,
        email_verified_at=None,
        phone_verified_at=None,
        email_otp_sent_count=0,
        phone_otp_sent_count=0,
        email_verify_attempt_count=0,
        phone_verify_attempt_count=0,
        email_last_otp_sent_at=None,
        phone_last_otp_sent_at=None,
    )


def _service(*, otp_store: _FakeOtpStore) -> AuthService:
    service = object.__new__(AuthService)
    service._settings = _settings()  # noqa: SLF001
    service._otp = otp_store  # type: ignore[assignment]  # noqa: SLF001
    service._phone = StagingFixedPhoneOtpSender(service._settings)  # noqa: SLF001
    service._session = _FakeSession()  # type: ignore[assignment]  # noqa: SLF001
    return service


@pytest.mark.asyncio
async def test_auth_service_hashes_fixed_challenge_through_existing_store() -> None:
    otp_store = _FakeOtpStore()
    pending = _pending()

    response = await _service(otp_store=otp_store)._send_channel_otp(pending, "phone")

    assert otp_store.stored == (pending.id, "phone", FIXED_CODE)
    assert response.phone_verified is False
    assert FIXED_CODE not in response.model_dump_json()


@pytest.mark.asyncio
async def test_unapproved_number_gets_same_response_but_fixed_code_is_not_stored() -> None:
    otp_store = _FakeOtpStore()
    pending = _pending(phone="+919999999999")

    response = await _service(otp_store=otp_store)._send_channel_otp(pending, "phone")

    assert response.message == "Verification code sent"
    assert otp_store.stored is not None
    assert otp_store.stored[:2] == (pending.id, "phone")
    assert otp_store.stored[2] != FIXED_CODE


@pytest.mark.asyncio
async def test_wrong_code_increments_existing_attempt_counter() -> None:
    otp_store = _FakeOtpStore(verifies=False)
    pending = _pending()

    with pytest.raises(UnauthorizedError, match="Invalid or expired verification code"):
        await _service(otp_store=otp_store)._verify_channel_otp(pending, "phone", "000000")

    assert pending.phone_verify_attempt_count == 1
    assert pending.phone_verified_at is None


def test_staging_secret_is_not_exposed_by_openapi() -> None:
    openapi = json.dumps(app.openapi())
    assert "STAGING_PHONE_OTP_CODE" not in openapi
    assert FIXED_CODE not in openapi
