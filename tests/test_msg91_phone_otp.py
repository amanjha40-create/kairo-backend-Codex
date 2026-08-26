from __future__ import annotations

import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.auth.service import AuthService
from app.config import Settings
from app.exceptions import (
    ConflictError,
    RateLimitError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationAppError,
)
from app.integrations.phone_otp.msg91 import Msg91PhoneOtpProvider


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        "jwt_secret_key": "test-jwt-secret-key-32-chars-minimum!!",
        "app_env": "staging",
        "phone_otp_backend": "msg91",
        "phone_otp_enabled": True,
        "msg91_auth_key": "server-auth-key",
        "msg91_template_id": "template-123",
        "msg91_sender_id": "KAIROD",
        "signup_otp_ttl_seconds": 300,
    }
    values.update(overrides)
    return Settings(**values)


class _FakeMsg91Client:
    def __init__(self, response: httpx.Response | Exception) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
    ) -> httpx.Response:
        self.calls.append((method, url, params))
        del headers
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class _FakeOtpStore:
    def __init__(self, state: dict[str, str] | None = None) -> None:
        self.state = state
        self.enforce_calls = 0
        self.store_calls: list[tuple[str, dict[str, str]]] = []
        self.clear_calls: list[str] = []

    async def enforce_send_rate(self, *_: object) -> None:
        self.enforce_calls += 1

    async def store_provider_state(  # noqa: ANN001
        self,
        signup_session_id,
        channel: str,
        state: dict[str, str],
    ) -> None:
        self.store_calls.append((channel, state))
        self.state = state
        self.last_session_id = signup_session_id

    async def get_provider_state(self, *_: object) -> dict[str, str] | None:
        return self.state

    async def clear(self, signup_session_id, channel: str) -> None:  # noqa: ANN001
        self.clear_calls.append(channel)
        self.state = None
        self.last_cleared_session_id = signup_session_id

    async def verify_and_consume(self, *_: object) -> bool:
        raise AssertionError("local OTP store should not be used for MSG91 verification")

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


def _pending(phone: str = "+919876543210") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        email="tester@example.com",
        phone=phone,
        email_verified_at=datetime.now(tz=UTC),
        phone_verified_at=None,
        email_otp_sent_count=1,
        phone_otp_sent_count=0,
        email_verify_attempt_count=0,
        phone_verify_attempt_count=0,
        email_last_otp_sent_at=datetime.now(tz=UTC),
        phone_last_otp_sent_at=None,
    )


def _service(
    *,
    otp_store: _FakeOtpStore,
    provider: object,
    settings: Settings | None = None,
) -> AuthService:
    service = object.__new__(AuthService)
    service._settings = settings or _settings()  # noqa: SLF001
    service._otp = otp_store  # type: ignore[assignment]  # noqa: SLF001
    service._email = AsyncMock()  # type: ignore[assignment]  # noqa: SLF001
    service._phone = None  # noqa: SLF001
    service._msg91_phone = provider  # type: ignore[assignment]  # noqa: SLF001
    service._session = _FakeSession()  # type: ignore[assignment]  # noqa: SLF001
    return service


def _response(
    status_code: int,
    payload: dict[str, object],
    *,
    method: str = "POST",
    path: str = "/otp",
) -> httpx.Response:
    request = httpx.Request(method, f"https://control.msg91.com/api/v5{path}")
    return httpx.Response(status_code, request=request, json=payload)


def _raw_response(
    status_code: int,
    body: str,
    *,
    method: str = "GET",
    path: str = "/otp/verify",
) -> httpx.Response:
    request = httpx.Request(method, f"https://control.msg91.com/api/v5{path}")
    return httpx.Response(
        status_code,
        request=request,
        content=body.encode("utf-8"),
        headers={"content-type": "application/json"},
    )


@pytest.mark.asyncio
async def test_msg91_send_returns_request_id_and_redacts_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = _FakeMsg91Client(_response(200, {"type": "success", "message": "req-123"}))
    provider = Msg91PhoneOtpProvider(
        _settings(),
        client=client,
    )

    with caplog.at_level(logging.INFO):
        result = await provider.send_signup_otp(to_phone="+919876543210")

    assert result.request_id == "req-123"
    assert client.calls[0][2]["otp_length"] == "6"
    assert "server-auth-key" not in caplog.text
    assert "+919876543210" not in caplog.text


@pytest.mark.asyncio
async def test_msg91_send_maps_invalid_phone_to_validation_error() -> None:
    provider = Msg91PhoneOtpProvider(
        _settings(),
        client=_FakeMsg91Client(
            _response(400, {"type": "202", "message": "Invalid mobile number"})
        ),
    )

    with pytest.raises(ValidationAppError, match="valid E.164"):
        await provider.send_signup_otp(to_phone="+919876543210")


@pytest.mark.asyncio
async def test_msg91_send_maps_rate_limit() -> None:
    provider = Msg91PhoneOtpProvider(
        _settings(),
        client=_FakeMsg91Client(
            _response(429, {"type": "rate_limited", "message": "Too many OTP requests"})
        ),
    )

    with pytest.raises(RateLimitError, match="Too many verification codes sent"):
        await provider.send_signup_otp(to_phone="+919876543210")


@pytest.mark.asyncio
async def test_msg91_resend_uses_retry_endpoint() -> None:
    client = _FakeMsg91Client(_response(200, {"type": "success", "message": "req-456"}))
    provider = Msg91PhoneOtpProvider(_settings(), client=client)

    result = await provider.resend_signup_otp(
        to_phone="+919876543210",
        prior_request_id="req-123",
    )

    assert result.request_id == "req-456"
    assert client.calls[0][0] == "GET"
    assert client.calls[0][1].endswith("/otp/retry")
    assert client.calls[0][2]["retrytype"] == "text"


@pytest.mark.asyncio
async def test_msg91_verify_maps_invalid_otp_to_unauthorized() -> None:
    provider = Msg91PhoneOtpProvider(
        _settings(),
        client=_FakeMsg91Client(_response(400, {"type": "error", "message": "Invalid OTP"})),
    )

    with pytest.raises(UnauthorizedError, match="Invalid or expired verification code"):
        await provider.verify_signup_otp(to_phone="+919876543210", code="123456")


@pytest.mark.asyncio
async def test_msg91_verify_accepts_explicit_success_body_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = _FakeMsg91Client(
        _response(
            200,
            {"type": "success", "message": "OTP verified success", "reqId": "req-123"},
            method="GET",
            path="/otp/verify",
        )
    )
    provider = Msg91PhoneOtpProvider(_settings(), client=client)

    with caplog.at_level(logging.INFO):
        await provider.verify_signup_otp(to_phone="+919876543210", code="123456")

    assert client.calls[0][0] == "GET"
    assert client.calls[0][1].endswith("/otp/verify")
    assert any(record.msg == "otp_verify_success" for record in caplog.records)
    assert not any(record.msg == "msg91_verify_rejected" for record in caplog.records)
    assert "123456" not in caplog.text
    assert "+919876543210" not in caplog.text


@pytest.mark.asyncio
async def test_msg91_verify_rejects_invalid_otp_body_even_with_http_200(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = Msg91PhoneOtpProvider(
        _settings(),
        client=_FakeMsg91Client(
            _response(
                200,
                {"type": "error", "message": "Invalid OTP"},
                method="GET",
                path="/otp/verify",
            )
        ),
    )

    with caplog.at_level(logging.INFO), pytest.raises(
        UnauthorizedError, match="Invalid or expired verification code"
    ):
        await provider.verify_signup_otp(to_phone="+919876543210", code="123456")

    assert any(record.msg == "msg91_verify_rejected" for record in caplog.records)
    assert not any(record.msg == "otp_verify_success" for record in caplog.records)


@pytest.mark.asyncio
async def test_msg91_verify_rejects_otp_not_match_body_even_with_http_200() -> None:
    provider = Msg91PhoneOtpProvider(
        _settings(),
        client=_FakeMsg91Client(
            _response(
                200,
                {"type": "error", "message": "OTP not match"},
                method="GET",
                path="/otp/verify",
            )
        ),
    )

    with pytest.raises(UnauthorizedError, match="Invalid or expired verification code"):
        await provider.verify_signup_otp(to_phone="+919876543210", code="123456")


@pytest.mark.asyncio
async def test_msg91_verify_rejects_expired_otp_body_even_with_http_200() -> None:
    provider = Msg91PhoneOtpProvider(
        _settings(),
        client=_FakeMsg91Client(
            _response(
                200,
                {"type": "error", "message": "OTP Expired"},
                method="GET",
                path="/otp/verify",
            )
        ),
    )

    with pytest.raises(UnauthorizedError, match="Invalid or expired verification code"):
        await provider.verify_signup_otp(to_phone="+919876543210", code="123456")


@pytest.mark.asyncio
async def test_msg91_verify_rejects_unknown_http_200_body_closed() -> None:
    provider = Msg91PhoneOtpProvider(
        _settings(),
        client=_FakeMsg91Client(
            _response(
                200,
                {"type": "success", "message": "Something unexpected"},
                method="GET",
                path="/otp/verify",
            )
        ),
    )

    with pytest.raises(ServiceUnavailableError, match="temporarily unavailable"):
        await provider.verify_signup_otp(to_phone="+919876543210", code="123456")


@pytest.mark.asyncio
async def test_msg91_verify_rejects_malformed_http_200_body() -> None:
    provider = Msg91PhoneOtpProvider(
        _settings(),
        client=_FakeMsg91Client(_raw_response(200, "{not-json")),
    )

    with pytest.raises(ServiceUnavailableError, match="temporarily unavailable"):
        await provider.verify_signup_otp(to_phone="+919876543210", code="123456")


@pytest.mark.asyncio
async def test_msg91_verify_maps_rate_limit_error_from_non_2xx_response() -> None:
    provider = Msg91PhoneOtpProvider(
        _settings(),
        client=_FakeMsg91Client(
            _response(
                429,
                {"type": "rate_limited", "message": "Too many verification attempts"},
                method="GET",
                path="/otp/verify",
            )
        ),
    )

    with pytest.raises(RateLimitError, match="Too many verification attempts"):
        await provider.verify_signup_otp(to_phone="+919876543210", code="123456")


@pytest.mark.asyncio
async def test_msg91_verify_timeout_maps_to_service_unavailable() -> None:
    provider = Msg91PhoneOtpProvider(
        _settings(),
        client=_FakeMsg91Client(httpx.ReadTimeout("timeout")),
    )

    with pytest.raises(ServiceUnavailableError, match="temporarily unavailable"):
        await provider.verify_signup_otp(to_phone="+919876543210", code="123456")


@pytest.mark.asyncio
async def test_auth_service_msg91_send_stores_provider_state_without_local_otp() -> None:
    otp_store = _FakeOtpStore()
    provider = SimpleNamespace(
        send_signup_otp=AsyncMock(
            return_value=SimpleNamespace(provider="msg91", request_id="req-123")
        ),
        resend_signup_otp=AsyncMock(),
        verify_signup_otp=AsyncMock(),
    )
    pending = _pending()

    response = await _service(
        otp_store=otp_store,
        provider=provider,
    )._send_channel_otp(pending, "phone")

    assert response.channel == "phone"
    assert pending.phone_otp_sent_count == 1
    assert otp_store.store_calls == [
        (
            "phone",
            {
                "provider": "msg91",
                "request_id": "req-123",
                "phone_e164": "+919876543210",
            },
        )
    ]


@pytest.mark.asyncio
async def test_auth_service_msg91_resend_reuses_stored_provider_state() -> None:
    otp_store = _FakeOtpStore(
        {
            "provider": "msg91",
            "request_id": "req-123",
            "phone_e164": "+919876543210",
        }
    )
    provider = SimpleNamespace(
        send_signup_otp=AsyncMock(),
        resend_signup_otp=AsyncMock(
            return_value=SimpleNamespace(provider="msg91", request_id="req-456")
        ),
        verify_signup_otp=AsyncMock(),
    )
    pending = _pending()

    await _service(otp_store=otp_store, provider=provider)._send_channel_otp(
        pending,
        "phone",
        resend=True,
    )

    provider.resend_signup_otp.assert_awaited_once_with(
        to_phone="+919876543210",
        prior_request_id="req-123",
    )


@pytest.mark.asyncio
async def test_auth_service_msg91_verify_marks_phone_verified_and_clears_state() -> None:
    otp_store = _FakeOtpStore(
        {
            "provider": "msg91",
            "request_id": "req-123",
            "phone_e164": "+919876543210",
        }
    )
    provider = SimpleNamespace(
        send_signup_otp=AsyncMock(),
        resend_signup_otp=AsyncMock(),
        verify_signup_otp=AsyncMock(return_value=None),
    )
    pending = _pending()

    response = await _service(otp_store=otp_store, provider=provider)._verify_channel_otp(
        pending,
        "phone",
        "123456",
    )

    assert response.phone_verified is True
    assert pending.phone_verified_at is not None
    assert otp_store.clear_calls == ["phone"]


@pytest.mark.asyncio
async def test_auth_service_msg91_verify_rejects_missing_state() -> None:
    otp_store = _FakeOtpStore(state=None)
    provider = SimpleNamespace(
        send_signup_otp=AsyncMock(),
        resend_signup_otp=AsyncMock(),
        verify_signup_otp=AsyncMock(),
    )
    pending = _pending()

    with pytest.raises(UnauthorizedError, match="Invalid or expired verification code"):
        await _service(otp_store=otp_store, provider=provider)._verify_channel_otp(
            pending,
            "phone",
            "123456",
        )

    assert pending.phone_verify_attempt_count == 1


@pytest.mark.asyncio
async def test_auth_service_msg91_verify_rejects_phone_mismatch() -> None:
    otp_store = _FakeOtpStore(
        {
            "provider": "msg91",
            "request_id": "req-123",
            "phone_e164": "+919999999999",
        }
    )
    provider = SimpleNamespace(
        send_signup_otp=AsyncMock(),
        resend_signup_otp=AsyncMock(),
        verify_signup_otp=AsyncMock(),
    )
    pending = _pending()

    with pytest.raises(ConflictError, match="does not match signup session"):
        await _service(otp_store=otp_store, provider=provider)._verify_channel_otp(
            pending,
            "phone",
            "123456",
        )

    assert pending.phone_verify_attempt_count == 1


@pytest.mark.asyncio
async def test_auth_service_msg91_verify_increments_attempts_on_invalid_code() -> None:
    otp_store = _FakeOtpStore(
        {
            "provider": "msg91",
            "request_id": "req-123",
            "phone_e164": "+919876543210",
        }
    )
    provider = SimpleNamespace(
        send_signup_otp=AsyncMock(),
        resend_signup_otp=AsyncMock(),
        verify_signup_otp=AsyncMock(
            side_effect=UnauthorizedError("Invalid or expired verification code")
        ),
    )
    pending = _pending()

    with pytest.raises(UnauthorizedError, match="Invalid or expired verification code"):
        await _service(otp_store=otp_store, provider=provider)._verify_channel_otp(
            pending,
            "phone",
            "123456",
        )

    assert pending.phone_verify_attempt_count == 1
    assert pending.phone_verified_at is None
    assert otp_store.clear_calls == []
