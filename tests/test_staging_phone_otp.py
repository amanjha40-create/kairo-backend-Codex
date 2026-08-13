"""Security coverage for the staging-only fixed phone OTP provider."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import httpx
import pytest
from botocore.exceptions import ClientError
from pydantic import ValidationError

from app.auth.service import AuthService
from app.auth.signup_otp import SignupOtpStore
from app.config import Settings
from app.exceptions import ConflictError, ServiceUnavailableError, UnauthorizedError
from app.integrations.phone_otp.sender import (
    Msg91ClientManagedPhoneOtpSender,
    SnsPhoneOtpSender,
    StagingFixedPhoneOtpSender,
    get_phone_otp_sender,
)
from app.integrations.phone_otp.verifier import Msg91PhoneOtpVerifier
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
    }
    values.update(overrides)
    return Settings(**values)


def test_staging_fixed_provider_requires_staging_or_explicit_controlled_testing() -> None:
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


def test_controlled_production_testing_allows_staging_fixed_with_valid_code() -> None:
    settings = _settings(
        app_env="production",
        controlled_testing=True,
        jwt_secret_key="production-jwt-secret-key-that-is-longer-than-forty-eight-characters",
        email_backend="smtp",
        smtp_host="smtp.example.com",
    )
    assert settings.controlled_testing is True
    assert settings.phone_otp_backend == "staging_fixed"


def test_controlled_production_testing_does_not_allow_console() -> None:
    with pytest.raises(ValidationError, match="must not be console"):
        _settings(
            app_env="production",
            controlled_testing=True,
            phone_otp_backend="console",
            jwt_secret_key="production-jwt-secret-key-that-is-longer-than-forty-eight-characters",
            email_backend="smtp",
            smtp_host="smtp.example.com",
        )


def test_controlled_production_testing_does_not_enable_sns() -> None:
    with pytest.raises(ValidationError, match="requires PHONE_OTP_BACKEND=staging_fixed"):
        _settings(
            app_env="production",
            controlled_testing=True,
            phone_otp_backend="sns",
            jwt_secret_key="production-jwt-secret-key-that-is-longer-than-forty-eight-characters",
            email_backend="smtp",
            smtp_host="smtp.example.com",
        )


def test_controlled_production_testing_requires_explicit_flag() -> None:
    with pytest.raises(ValidationError, match="forbidden in APP_ENV=production"):
        _settings(
            app_env="production",
            controlled_testing=False,
            jwt_secret_key="production-jwt-secret-key-that-is-longer-than-forty-eight-characters",
            email_backend="smtp",
            smtp_host="smtp.example.com",
        )


@pytest.mark.parametrize(
    "code",
    (None, "12345", "1234567", "abcdef"),
)
def test_controlled_production_testing_requires_six_digit_code(code: str | None) -> None:
    with pytest.raises(ValidationError, match="STAGING_PHONE_OTP_CODE|exactly six digits"):
        _settings(
            app_env="production",
            controlled_testing=True,
            staging_phone_otp_code=code,
            jwt_secret_key="production-jwt-secret-key-that-is-longer-than-forty-eight-characters",
            email_backend="smtp",
            smtp_host="smtp.example.com",
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"staging_phone_otp_code": None}, "STAGING_PHONE_OTP_CODE"),
        ({"staging_phone_otp_code": "12345"}, "exactly six digits"),
    ),
)
def test_staging_fixed_provider_validates_secret(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _settings(**overrides)


def test_provider_factory_selects_staging_fixed() -> None:
    assert isinstance(get_phone_otp_sender(_settings()), StagingFixedPhoneOtpSender)


def test_provider_factory_selects_sns() -> None:
    sender = get_phone_otp_sender(
        _settings(phone_otp_backend="sns", aws_region="us-east-1"),
    )
    assert isinstance(sender, SnsPhoneOtpSender)


def test_provider_factory_selects_msg91_client_managed_sender() -> None:
    assert isinstance(
        get_phone_otp_sender(_settings(phone_otp_backend="msg91", msg91_auth_key="secret-key")),
        Msg91ClientManagedPhoneOtpSender,
    )


def test_unknown_provider_fails_closed() -> None:
    with pytest.raises(ValidationError, match="must be one of: console, staging_fixed, sns, msg91"):
        _settings(phone_otp_backend="unknown")


def test_provider_factory_does_not_fallback_to_console() -> None:
    settings = Mock(phone_otp_backend="unknown")
    with pytest.raises(ValueError, match="Unsupported PHONE_OTP_BACKEND"):
        get_phone_otp_sender(settings)  # type: ignore[arg-type]


def test_sns_provider_requires_region() -> None:
    with pytest.raises(ValidationError, match="AWS_REGION is required"):
        _settings(phone_otp_backend="sns", aws_region=None)


def test_msg91_provider_requires_auth_key() -> None:
    with pytest.raises(ValidationError, match="MSG91_AUTH_KEY is required"):
        _settings(phone_otp_backend="msg91", msg91_auth_key=None)


@pytest.mark.asyncio
async def test_sns_provider_publishes_otp_without_logging_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = _settings(phone_otp_backend="sns", aws_region="us-east-1")
    client = Mock()
    with patch("app.integrations.phone_otp.sender.boto3.client", return_value=client):
        sender = SnsPhoneOtpSender(settings)
        with caplog.at_level(logging.INFO):
            await sender.send_signup_otp(to_phone=ALLOWED_PHONE, code="135790", ttl_minutes=10)

    client.publish.assert_called_once_with(
        PhoneNumber=ALLOWED_PHONE,
        Message="Your Kairo verification code is 135790. It expires in 10 minutes.",
    )
    assert "135790" not in caplog.text
    assert ALLOWED_PHONE not in caplog.text


@pytest.mark.asyncio
async def test_sns_provider_propagates_delivery_failure_without_logging_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = _settings(phone_otp_backend="sns", aws_region="us-east-1")
    client = Mock()
    client.publish.side_effect = ClientError(
        {"Error": {"Code": "Throttled", "Message": "delivery failed"}},
        "Publish",
    )
    with patch("app.integrations.phone_otp.sender.boto3.client", return_value=client):
        sender = SnsPhoneOtpSender(settings)
        with caplog.at_level(logging.INFO), pytest.raises(ClientError):
            await sender.send_signup_otp(to_phone=ALLOWED_PHONE, code="135790", ttl_minutes=10)

    assert "135790" not in caplog.text
    assert ALLOWED_PHONE not in caplog.text


@pytest.mark.asyncio
async def test_valid_number_uses_injected_code_without_logging_secret(
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


def test_any_valid_staging_number_uses_injected_code() -> None:
    sender = StagingFixedPhoneOtpSender(_settings())

    challenge = sender.challenge_code(to_phone="+919999999999", generated_code="111111")

    assert challenge == FIXED_CODE


class _OtpRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def eval(self, _: str, __: int, key: str, expected_hash: str) -> int:
        if self.values.get(key) != expected_hash:
            return 0
        del self.values[key]
        return 1

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.values.pop(key, None)

    async def set(self, key: str, value: str, **kwargs: object) -> bool | None:
        if kwargs.get("nx") and key in self.values:
            return None
        self.values[key] = value
        return True


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
    def __init__(self, *, verifies: bool = True, replay_allows: bool = True) -> None:
        self.verifies = verifies
        self.replay_allows = replay_allows
        self.stored: tuple[UUID, str, str] | None = None

    async def enforce_send_rate(self, *_: object) -> None:
        return None

    async def store_otp(self, signup_session_id: UUID, channel: str, code: str) -> None:
        self.stored = (signup_session_id, channel, code)

    async def verify_and_consume(self, *_: object) -> bool:
        return self.verifies

    async def consume_msg91_access_token_once(self, *_: object) -> bool:
        return self.replay_allows

    def seconds_until_resend_allowed(self, _: object) -> int:
        return 0


class _FakeSession:
    def __init__(self) -> None:
        self.flush_count = 0
        self.commit_count = 0

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:
        self.commit_count += 1


class _FakeEmailSender:
    def __init__(self, *, exc: Exception | None = None) -> None:
        self.exc = exc
        self.calls: list[tuple[str, str, int]] = []

    async def send_signup_otp(self, *, to_email: str, code: str, ttl_minutes: int) -> None:
        self.calls.append((to_email, code, ttl_minutes))
        if self.exc is not None:
            raise self.exc


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


def _service(*, otp_store: _FakeOtpStore, email_sender: _FakeEmailSender | None = None) -> AuthService:
    service = object.__new__(AuthService)
    service._settings = _settings()  # noqa: SLF001
    service._otp = otp_store  # type: ignore[assignment]  # noqa: SLF001
    service._email = email_sender or _FakeEmailSender()  # type: ignore[assignment]  # noqa: SLF001
    service._phone = StagingFixedPhoneOtpSender(service._settings)  # noqa: SLF001
    service._phone_verifier = None  # type: ignore[assignment]  # noqa: SLF001
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
async def test_email_signup_channel_routes_through_email_sender_and_updates_counters() -> None:
    otp_store = _FakeOtpStore()
    email_sender = _FakeEmailSender()
    pending = _pending()

    response = await _service(otp_store=otp_store, email_sender=email_sender)._send_channel_otp(pending, "email")

    assert response.channel == "email"
    assert otp_store.stored is not None
    assert email_sender.calls == [("tester@example.com", otp_store.stored[2], 10)]
    assert pending.email_otp_sent_count == 1
    assert pending.email_last_otp_sent_at is not None


@pytest.mark.asyncio
async def test_email_signup_channel_does_not_increment_counters_when_delivery_fails() -> None:
    otp_store = _FakeOtpStore()
    email_sender = _FakeEmailSender(exc=ServiceUnavailableError("Unable to send verification email"))
    pending = _pending()

    with pytest.raises(ServiceUnavailableError, match="Unable to send verification email"):
        await _service(otp_store=otp_store, email_sender=email_sender)._send_channel_otp(pending, "email")

    assert pending.email_otp_sent_count == 0
    assert pending.email_last_otp_sent_at is None


@pytest.mark.asyncio
async def test_different_valid_number_stores_same_staging_challenge() -> None:
    otp_store = _FakeOtpStore()
    pending = _pending(phone="+919999999999")

    response = await _service(otp_store=otp_store)._send_channel_otp(pending, "phone")

    assert response.message == "Verification code sent"
    assert otp_store.stored is not None
    assert otp_store.stored[:2] == (pending.id, "phone")
    assert otp_store.stored[2] == FIXED_CODE


@pytest.mark.asyncio
async def test_wrong_code_increments_existing_attempt_counter() -> None:
    otp_store = _FakeOtpStore(verifies=False)
    pending = _pending()

    with pytest.raises(UnauthorizedError, match="Invalid or expired verification code"):
        await _service(otp_store=otp_store)._verify_channel_otp(pending, "phone", "000000")

    assert pending.phone_verify_attempt_count == 1
    assert pending.phone_verified_at is None


class _FakeMsg91Client:
    def __init__(self, response: httpx.Response | Exception) -> None:
        self._response = response

    async def post(self, *args: object, **kwargs: object) -> httpx.Response:
        del args, kwargs
        if isinstance(self._response, Exception):
            raise self._response
        return self._response

    async def aclose(self) -> None:
        return None


def _msg91_response(status_code: int, payload: dict[str, object]) -> httpx.Response:
    request = httpx.Request("POST", "https://control.msg91.com/api/v5/widget/verifyAccessToken")
    return httpx.Response(status_code, request=request, json=payload)


@pytest.mark.asyncio
async def test_msg91_verifier_accepts_valid_token_without_logging_secret_material(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = _settings(phone_otp_backend="msg91", msg91_auth_key="server-auth-key")
    verifier = Msg91PhoneOtpVerifier(
        settings,
        client=_FakeMsg91Client(_msg91_response(200, {"data": {"mobile": "8767299299"}})),
    )

    with caplog.at_level(logging.INFO):
        result = await verifier.verify_signup_access_token(access_token="very-secret-access-token")

    assert result.verified_identifier == "8767299299"
    assert "server-auth-key" not in caplog.text
    assert "very-secret-access-token" not in caplog.text
    assert "8767299299" not in caplog.text


@pytest.mark.asyncio
async def test_msg91_verifier_rejects_invalid_token() -> None:
    settings = _settings(phone_otp_backend="msg91", msg91_auth_key="server-auth-key")
    verifier = Msg91PhoneOtpVerifier(
        settings,
        client=_FakeMsg91Client(_msg91_response(401, {"message": "invalid token"})),
    )

    with pytest.raises(UnauthorizedError, match="Invalid or expired phone verification token"):
        await verifier.verify_signup_access_token(access_token="invalid-token")


@pytest.mark.asyncio
async def test_msg91_verifier_rejects_missing_identifier() -> None:
    settings = _settings(phone_otp_backend="msg91", msg91_auth_key="server-auth-key")
    verifier = Msg91PhoneOtpVerifier(
        settings,
        client=_FakeMsg91Client(_msg91_response(200, {"status": "success"})),
    )

    with pytest.raises(UnauthorizedError, match="Invalid or expired phone verification token"):
        await verifier.verify_signup_access_token(access_token="valid-token")


@pytest.mark.asyncio
async def test_msg91_verifier_surfaces_provider_outage() -> None:
    settings = _settings(phone_otp_backend="msg91", msg91_auth_key="server-auth-key")
    verifier = Msg91PhoneOtpVerifier(
        settings,
        client=_FakeMsg91Client(_msg91_response(503, {"message": "temporarily unavailable"})),
    )

    with pytest.raises(ServiceUnavailableError, match="Phone verification service unavailable"):
        await verifier.verify_signup_access_token(access_token="valid-token")


@pytest.mark.asyncio
async def test_msg91_verifier_surfaces_timeout() -> None:
    settings = _settings(phone_otp_backend="msg91", msg91_auth_key="server-auth-key")
    verifier = Msg91PhoneOtpVerifier(
        settings,
        client=_FakeMsg91Client(httpx.ReadTimeout("timeout")),
    )

    with pytest.raises(ServiceUnavailableError, match="Phone verification service unavailable"):
        await verifier.verify_signup_access_token(access_token="valid-token")


@pytest.mark.asyncio
async def test_msg91_phone_verification_accepts_normalized_equivalent_phone() -> None:
    otp_store = _FakeOtpStore()
    pending = _pending(phone="+918767299299")
    service = _service(otp_store=otp_store)
    service._settings = _settings(phone_otp_backend="msg91", msg91_auth_key="server-auth-key")  # noqa: SLF001

    async def _verify_signup_access_token(**_: object) -> SimpleNamespace:
        return SimpleNamespace(verified_identifier="8767299299")

    service._phone_verifier = SimpleNamespace(  # type: ignore[assignment]  # noqa: SLF001
        verify_signup_access_token=_verify_signup_access_token,
    )

    response = await service._verify_signup_phone_with_msg91(  # noqa: SLF001
        pending,
        access_token="msg91-access-token",
    )

    assert pending.phone_verified_at is not None
    assert response.phone_verified is True
    assert response.message == "Phone verified"


@pytest.mark.asyncio
async def test_msg91_phone_verification_preserves_already_verified_idempotency() -> None:
    otp_store = _FakeOtpStore()
    pending = _pending(phone="+918767299299")
    pending.phone_verified_at = datetime.now(tz=UTC)
    service = _service(otp_store=otp_store)
    service._settings = _settings(phone_otp_backend="msg91", msg91_auth_key="server-auth-key")  # noqa: SLF001

    async def _verify_signup_access_token(**_: object) -> SimpleNamespace:
        raise AssertionError("verifier should not be called when signup is already phone-verified")

    service._phone_verifier = SimpleNamespace(  # type: ignore[assignment]  # noqa: SLF001
        verify_signup_access_token=_verify_signup_access_token,
    )

    response = await service._verify_signup_phone_with_msg91(  # noqa: SLF001
        pending,
        access_token="msg91-access-token",
    )

    assert response.phone_verified is True
    assert response.message == "Phone already verified"


@pytest.mark.asyncio
async def test_msg91_phone_verification_fails_closed_on_identifier_mismatch() -> None:
    otp_store = _FakeOtpStore()
    pending = _pending(phone="+918767299299")
    service = _service(otp_store=otp_store)
    service._settings = _settings(phone_otp_backend="msg91", msg91_auth_key="server-auth-key")  # noqa: SLF001

    async def _verify_signup_access_token(**_: object) -> SimpleNamespace:
        return SimpleNamespace(verified_identifier="+919999999999")

    service._phone_verifier = SimpleNamespace(  # type: ignore[assignment]  # noqa: SLF001
        verify_signup_access_token=_verify_signup_access_token,
    )

    with pytest.raises(ConflictError, match="does not match signup session"):
        await service._verify_signup_phone_with_msg91(pending, access_token="msg91-access-token")  # noqa: SLF001

    assert pending.phone_verify_attempt_count == 1
    assert pending.phone_verified_at is None


@pytest.mark.asyncio
async def test_msg91_phone_verification_rejects_replay() -> None:
    otp_store = _FakeOtpStore(replay_allows=False)
    pending = _pending(phone="+918767299299")
    service = _service(otp_store=otp_store)
    service._settings = _settings(phone_otp_backend="msg91", msg91_auth_key="server-auth-key")  # noqa: SLF001

    async def _verify_signup_access_token(**_: object) -> SimpleNamespace:
        return SimpleNamespace(verified_identifier="+918767299299")

    service._phone_verifier = SimpleNamespace(  # type: ignore[assignment]  # noqa: SLF001
        verify_signup_access_token=_verify_signup_access_token,
    )

    with pytest.raises(UnauthorizedError, match="Invalid or expired phone verification token"):
        await service._verify_signup_phone_with_msg91(pending, access_token="msg91-access-token")  # noqa: SLF001


@pytest.mark.asyncio
async def test_msg91_backend_rejects_code_only_phone_verification() -> None:
    pending = _pending(phone="+918767299299")
    service = _service(otp_store=_FakeOtpStore())
    service._settings = _settings(phone_otp_backend="msg91", msg91_auth_key="server-auth-key")  # noqa: SLF001

    async def _load_active_pending(*_: object, **__: object) -> SimpleNamespace:
        return pending

    service._load_active_pending = _load_active_pending  # type: ignore[method-assign]  # noqa: SLF001
    service._assert_signup_kind = lambda *_: None  # type: ignore[method-assign]  # noqa: SLF001

    from app.schemas.auth import SignupPhoneVerifyRequest

    with pytest.raises(ConflictError, match="access token is required"):
        await service.verify_signup_phone(
            SignupPhoneVerifyRequest(signup_session_id=pending.id, code="123456"),
        )


def test_staging_secret_is_not_exposed_by_openapi() -> None:
    openapi = json.dumps(app.openapi())
    assert "STAGING_PHONE_OTP_CODE" not in openapi
    assert FIXED_CODE not in openapi
