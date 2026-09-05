"""HTTP contracts for the state-bound Google App Link handoff."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.services import get_auth_service
from app.infrastructure.redis.deps import get_redis
from app.main import app
from app.schemas.auth import GoogleHandoffExchangeResponse, GoogleAuthOutcome, SignupStartResponse


class _GoogleAuth:
    google_app_handoff_uri = "https://staging-api.kairoid.com/auth/google/complete"

    async def start_google_oauth(self):
        from app.schemas.auth import OAuthAuthUrlResponse
        return OAuthAuthUrlResponse(provider="google", auth_url="https://accounts.google.test/?state=opaque&code_challenge=challenge")

    async def complete_google_callback(self, **_kwargs):
        return "opaque-handoff-code-0123456789"

    async def exchange_google_handoff(self, code):
        if code != "opaque-handoff-code-0123456789":
            return GoogleHandoffExchangeResponse(outcome=GoogleAuthOutcome.AUTH_FAILED, message="safe")
        return GoogleHandoffExchangeResponse(
            outcome=GoogleAuthOutcome.PHONE_VERIFICATION_REQUIRED,
            message="safe",
            signup=SignupStartResponse(signup_session_id=uuid4(), email_masked="go***@example.com", phone_masked="", email_verified=True, phone_verified=False, email_resend_after_seconds=0, phone_resend_after_seconds=0, expires_in_seconds=3600),
        )


class _Redis:
    async def eval(self, *_args):
        return 1


@pytest.mark.asyncio
async def test_google_callback_redirects_only_with_opaque_handoff_code() -> None:
    app.dependency_overrides[get_auth_service] = lambda: _GoogleAuth()
    app.dependency_overrides[get_redis] = lambda: _Redis()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False) as client:
        response = await client.get("/api/v1/auth/google/callback?code=provider-code&state=state")
    app.dependency_overrides.clear()
    assert response.status_code == 303
    location = response.headers["location"]
    assert location == "https://staging-api.kairoid.com/auth/google/complete?code=opaque-handoff-code-0123456789"
    assert all(value not in location for value in ("access_token", "refresh_token", "@", "provider-code"))


@pytest.mark.asyncio
async def test_google_handoff_exchange_is_safe_for_phone_continuation() -> None:
    app.dependency_overrides[get_auth_service] = lambda: _GoogleAuth()
    app.dependency_overrides[get_redis] = lambda: _Redis()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/auth/google/handoff/exchange", json={"code": "opaque-handoff-code-0123456789"})
    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "PHONE_VERIFICATION_REQUIRED"
    assert body["tokens"] is None
    assert body["signup"]["email_verified"] is True
