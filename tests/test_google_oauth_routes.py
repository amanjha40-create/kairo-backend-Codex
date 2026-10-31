"""HTTP contracts for the state-bound Google App Link handoff."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.services import get_auth_service
from app.auth.service import GoogleCallbackHandoff
from app.infrastructure.redis.deps import get_redis
from app.main import app
from app.schemas.auth import (
    GoogleAuthOutcome,
    GoogleHandoffExchangeResponse,
    GoogleOAuthClientTarget,
    OAuthAuthUrlResponse,
    SignupStartResponse,
)


class _GoogleAuth:
    google_app_handoff_uri = "https://staging-api.kairoid.com/auth/google/complete"
    started_target = GoogleOAuthClientTarget.ANDROID_PRODUCTION
    callback_target = GoogleOAuthClientTarget.ANDROID_PRODUCTION
    exchanged_target = GoogleOAuthClientTarget.ANDROID_PRODUCTION

    async def start_google_oauth(
        self,
        client_target=GoogleOAuthClientTarget.ANDROID_PRODUCTION,
    ):
        self.started_target = client_target
        return OAuthAuthUrlResponse(
            provider="google",
            auth_url="https://accounts.google.test/?state=opaque&code_challenge=challenge",
        )

    async def complete_google_callback(self, **_kwargs):
        return GoogleCallbackHandoff("opaque-handoff-code-0123456789", self.callback_target)

    def google_handoff_uri_for(self, client_target):
        if client_target is GoogleOAuthClientTarget.ANDROID_QA:
            return "com.kairoid.app.qa://oauth/google/callback"
        return self.google_app_handoff_uri

    async def exchange_google_handoff(self, code, client_target):
        self.exchanged_target = client_target
        if code != "opaque-handoff-code-0123456789":
            return GoogleHandoffExchangeResponse(
                outcome=GoogleAuthOutcome.AUTH_FAILED,
                message="safe",
            )
        return GoogleHandoffExchangeResponse(
            outcome=GoogleAuthOutcome.PHONE_VERIFICATION_REQUIRED,
            message="safe",
            signup=SignupStartResponse(
                signup_session_id=uuid4(),
                email_masked="go***@example.com",
                phone_masked="",
                email_verified=True,
                phone_verified=False,
                email_resend_after_seconds=0,
                phone_resend_after_seconds=0,
                expires_in_seconds=3600,
            ),
        )


class _Redis:
    async def eval(self, *_args):
        return 1


def test_google_oauth_openapi_exposes_only_allowlisted_client_target() -> None:
    app.openapi_schema = None
    schema = app.openapi()
    start = schema["paths"]["/api/v1/auth/google/url"]["get"]
    parameter = next(item for item in start["parameters"] if item["name"] == "client_target")
    target_schema = schema["components"]["schemas"]["GoogleOAuthClientTarget"]
    assert parameter["schema"]["default"] == "android_production"
    assert target_schema["enum"] == ["android_production", "android_qa"]

    exchange = schema["components"]["schemas"]["GoogleHandoffExchangeRequest"]
    assert exchange["properties"]["client_target"]["default"] == "android_production"


@pytest.mark.asyncio
async def test_google_callback_redirects_only_with_opaque_handoff_code() -> None:
    auth = _GoogleAuth()
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_redis] = lambda: _Redis()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        response = await client.get(
            "/api/v1/auth/google/callback",
            params={
                "code": "provider-code",
                "state": "state",
                "client_target": "android_qa",
                "return_uri": "https://attacker.example",
            },
        )
    app.dependency_overrides.clear()
    assert response.status_code == 303
    location = response.headers["location"]
    assert location == "https://staging-api.kairoid.com/auth/google/complete?code=opaque-handoff-code-0123456789"
    assert all(
        value not in location
        for value in ("access_token", "refresh_token", "@", "provider-code")
    )


@pytest.mark.asyncio
async def test_google_qa_callback_uses_only_fixed_custom_uri_and_opaque_code() -> None:
    auth = _GoogleAuth()
    auth.callback_target = GoogleOAuthClientTarget.ANDROID_QA
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_redis] = lambda: _Redis()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        response = await client.get(
            "/api/v1/auth/google/callback?code=provider-code&state=state"
        )
    app.dependency_overrides.clear()
    assert response.status_code == 303
    location = response.headers["location"]
    assert location == (
        "com.kairoid.app.qa://oauth/google/callback?code="
        "opaque-handoff-code-0123456789"
    )
    assert all(
        value not in location
        for value in ("access_token", "refresh_token", "id_token", "@", "provider-code")
    )


@pytest.mark.asyncio
async def test_google_start_binds_only_allowlisted_client_targets() -> None:
    auth = _GoogleAuth()
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_redis] = lambda: _Redis()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        production = await client.get("/api/v1/auth/google/url")
        assert production.status_code == 200
        assert auth.started_target is GoogleOAuthClientTarget.ANDROID_PRODUCTION
        qa = await client.get(
            "/api/v1/auth/google/url", params={"client_target": "android_qa"}
        )
        assert qa.status_code == 200
        assert auth.started_target is GoogleOAuthClientTarget.ANDROID_QA
        invalid = await client.get(
            "/api/v1/auth/google/url",
            params={"client_target": "https://attacker.example"},
        )
        assert invalid.status_code == 422
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_google_handoff_exchange_is_safe_for_phone_continuation() -> None:
    auth = _GoogleAuth()
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_redis] = lambda: _Redis()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/google/handoff/exchange",
            json={"code": "opaque-handoff-code-0123456789"},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "PHONE_VERIFICATION_REQUIRED"
    assert body["tokens"] is None
    assert body["signup"]["email_verified"] is True
    assert auth.exchanged_target is GoogleOAuthClientTarget.ANDROID_PRODUCTION


@pytest.mark.asyncio
async def test_google_qa_handoff_exchange_is_explicitly_client_bound() -> None:
    auth = _GoogleAuth()
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_redis] = lambda: _Redis()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/google/handoff/exchange",
            json={
                "code": "opaque-handoff-code-0123456789",
                "client_target": "android_qa",
            },
        )
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert auth.exchanged_target is GoogleOAuthClientTarget.ANDROID_QA
