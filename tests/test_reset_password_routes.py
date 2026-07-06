"""Route-contract tests for forgot/reset password endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.services import get_auth_service
from app.infrastructure.redis.deps import get_redis
from app.main import app
from app.schemas.auth import ForgotPasswordResponse, ResetPasswordResponse


class FakeAuthService:
    def __init__(self) -> None:
        self.forgot_payloads: list[object] = []
        self.reset_payloads: list[object] = []

    async def forgot_password(self, payload) -> ForgotPasswordResponse:  # noqa: ANN001
        self.forgot_payloads.append(payload)
        return ForgotPasswordResponse()

    async def reset_password(self, payload) -> ResetPasswordResponse:  # noqa: ANN001
        self.reset_payloads.append(payload)
        return ResetPasswordResponse()


class FakeRedis:
    async def eval(self, *args, **kwargs) -> int:  # noqa: ANN002, ANN003
        return 1

    async def ttl(self, *args, **kwargs) -> int:  # noqa: ANN002, ANN003
        return 60


@pytest.mark.asyncio
async def test_forgot_password_returns_generic_response() -> None:
    fake = FakeAuthService()
    app.dependency_overrides[get_auth_service] = lambda: fake
    app.dependency_overrides[get_redis] = lambda: FakeRedis()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "person@example.com"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 202
    assert response.json()["message"].startswith("If an account exists")
    assert len(fake.forgot_payloads) == 1


@pytest.mark.asyncio
async def test_reset_password_accepts_valid_payload() -> None:
    fake = FakeAuthService()
    app.dependency_overrides[get_auth_service] = lambda: fake
    app.dependency_overrides[get_redis] = lambda: FakeRedis()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": "this-is-a-reset-token-value-123456",
                "new_password": "StrongPassword123!",
                "confirm_password": "StrongPassword123!",
            },
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["message"] == "Password reset successful."
    assert len(fake.reset_payloads) == 1
