"""Route-contract coverage for staged dual-OTP signup and auth session APIs."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.services import get_auth_service
from app.infrastructure.redis.deps import get_redis
from app.main import app
from app.schemas.auth import (
    ForgotPasswordResponse,
    LoginRequest,
    SignupChannelSendResponse,
    SignupChannelVerifyResponse,
    SignupStartResponse,
    TokenResponse,
)


class FakeAuthService:
    async def start_signup(self, payload) -> SignupStartResponse:  # noqa: ANN001
        assert payload.phone == "+919876543210"
        return SignupStartResponse(
            signup_session_id=uuid4(),
            email_masked="am***@example.com",
            phone_masked="+91******3210",
            email_verified=False,
            phone_verified=False,
            email_resend_after_seconds=0,
            phone_resend_after_seconds=0,
            expires_in_seconds=86400,
            message="Signup session created",
        )

    async def send_signup_email_otp(self, payload) -> SignupChannelSendResponse:  # noqa: ANN001
        return SignupChannelSendResponse(
            signup_session_id=payload.signup_session_id,
            channel="email",
            verified=False,
            email_verified=False,
            phone_verified=False,
            resend_after_seconds=30,
            expires_in_seconds=300,
            email_masked="am***@example.com",
            phone_masked="+91******3210",
        )

    async def resend_signup_email_otp(self, payload) -> SignupChannelSendResponse:  # noqa: ANN001
        return await self.send_signup_email_otp(payload)

    async def verify_signup_email(self, payload) -> SignupChannelVerifyResponse:  # noqa: ANN001
        return SignupChannelVerifyResponse(
            signup_session_id=payload.signup_session_id,
            channel="email",
            email_verified=True,
            phone_verified=False,
            message="Email verified",
        )

    async def send_signup_phone_otp(self, payload) -> SignupChannelSendResponse:  # noqa: ANN001
        return SignupChannelSendResponse(
            signup_session_id=payload.signup_session_id,
            channel="phone",
            verified=False,
            email_verified=True,
            phone_verified=False,
            resend_after_seconds=30,
            expires_in_seconds=300,
            email_masked="am***@example.com",
            phone_masked="+91******3210",
        )

    async def resend_signup_phone_otp(self, payload) -> SignupChannelSendResponse:  # noqa: ANN001
        return await self.send_signup_phone_otp(payload)

    async def verify_signup_phone(self, payload) -> SignupChannelVerifyResponse:  # noqa: ANN001
        return SignupChannelVerifyResponse(
            signup_session_id=payload.signup_session_id,
            channel="phone",
            email_verified=True,
            phone_verified=True,
            message="Phone verified",
        )

    async def complete_signup(self, payload) -> TokenResponse:  # noqa: ANN001
        return TokenResponse(
            access_token="access-token",
            refresh_token="refresh-token",
            expires_in=900,
        )

    async def login(self, payload: LoginRequest) -> TokenResponse:
        assert payload.email == "aman@example.com"
        return TokenResponse(
            access_token="access-token",
            refresh_token="refresh-token",
            expires_in=900,
        )

    async def refresh(self, payload) -> TokenResponse:  # noqa: ANN001
        return TokenResponse(
            access_token="new-access-token",
            refresh_token="new-refresh-token",
            expires_in=900,
        )

    async def logout(self, payload) -> None:  # noqa: ANN001
        assert payload.refresh_token == "refresh-token"

    async def forgot_password(self, payload) -> ForgotPasswordResponse:  # noqa: ANN001
        return ForgotPasswordResponse()


class FakeRedis:
    async def eval(self, *args, **kwargs) -> int:  # noqa: ANN002, ANN003
        return 1

    async def ttl(self, *args, **kwargs) -> int:  # noqa: ANN002, ANN003
        return 60


@pytest.mark.asyncio
async def test_dual_signup_routes_expose_phase1_contract() -> None:
    fake = FakeAuthService()
    app.dependency_overrides[get_auth_service] = lambda: fake
    app.dependency_overrides[get_redis] = lambda: FakeRedis()
    signup_session_id = str(uuid4())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        start = await client.post(
            "/api/v1/auth/signup/start",
            json={
                "full_name": "Aman Jha",
                "email": "aman@example.com",
                "phone": "+919876543210",
                "password": "StrongPassword123!",
            },
        )
        email_send = await client.post(
            "/api/v1/auth/signup/email/send",
            json={"signup_session_id": signup_session_id},
        )
        email_verify = await client.post(
            "/api/v1/auth/signup/email/verify",
            json={"signup_session_id": signup_session_id, "code": "123456"},
        )
        phone_send = await client.post(
            "/api/v1/auth/signup/phone/send",
            json={"signup_session_id": signup_session_id},
        )
        phone_verify = await client.post(
            "/api/v1/auth/signup/phone/verify",
            json={"signup_session_id": signup_session_id, "code": "123456"},
        )
        complete = await client.post(
            "/api/v1/auth/signup/complete",
            json={"signup_session_id": signup_session_id},
        )

    app.dependency_overrides.clear()

    assert start.status_code == 201
    assert start.json()["phone_masked"] == "+91******3210"

    assert email_send.status_code == 200
    assert email_send.json()["channel"] == "email"
    assert email_send.json()["resend_after_seconds"] == 30

    assert email_verify.status_code == 200
    assert email_verify.json()["email_verified"] is True
    assert email_verify.json()["phone_verified"] is False

    assert phone_send.status_code == 200
    assert phone_send.json()["channel"] == "phone"

    assert phone_verify.status_code == 200
    assert phone_verify.json()["phone_verified"] is True

    assert complete.status_code == 200
    assert complete.json()["access_token"] == "access-token"
    assert complete.json()["refresh_token"] == "refresh-token"


@pytest.mark.asyncio
async def test_login_refresh_and_logout_contracts_remain_stable() -> None:
    fake = FakeAuthService()
    app.dependency_overrides[get_auth_service] = lambda: fake
    app.dependency_overrides[get_redis] = lambda: FakeRedis()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "aman@example.com", "password": "StrongPassword123!"},
        )
        refresh = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "refresh-token"},
        )
        logout = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "refresh-token"},
        )

    app.dependency_overrides.clear()

    assert login.status_code == 200
    assert login.json()["token_type"] == "bearer"

    assert refresh.status_code == 200
    assert refresh.json()["access_token"] == "new-access-token"

    assert logout.status_code == 204
    assert logout.content == b""


@pytest.mark.asyncio
async def test_phase1_routes_validate_nested_payloads() -> None:
    fake = FakeAuthService()
    app.dependency_overrides[get_auth_service] = lambda: fake
    app.dependency_overrides[get_redis] = lambda: FakeRedis()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/signup/phone/verify",
            json={"signup_session_id": str(uuid4()), "code": "12ab56"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert isinstance(body["error"]["details"], list)
