from __future__ import annotations

from collections import defaultdict

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.routes.public_contact import (
    get_public_contact_service,
    router,
)
from app.config import Settings, get_settings
from app.exceptions import AppException, ServiceUnavailableError
from app.exceptions.handlers import (
    app_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.infrastructure.redis.deps import get_redis
from app.schemas.public_contact import PublicContactAcceptedResponse, PublicContactRequest


def _settings(**overrides: object) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        "jwt_secret_key": "test-jwt-secret-key-32-chars-minimum!!",
        "cors_origins": ["https://kairoid.com"],
        "contact_rate_limit_max_requests": 5,
        "contact_rate_limit_window_seconds": 300,
    }
    base.update(overrides)
    return Settings(**base)


class _FakeRedis:
    def __init__(self) -> None:
        self.counts = defaultdict(int)

    async def eval(self, _script: str, _keys_count: int, key: str, _window: str) -> int:
        self.counts[key] += 1
        return self.counts[key]

    async def ttl(self, _key: str) -> int:
        return 60


def _build_test_app() -> FastAPI:
    application = FastAPI()
    application.include_router(router, prefix="/api/v1")
    application.add_exception_handler(AppException, app_exception_handler)
    application.add_exception_handler(StarletteHTTPException, http_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
    return application


class _RecordingContactService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def submit(
        self,
        payload: PublicContactRequest,
        *,
        request_id: str,
        client_host: str | None,
    ):
        self.calls.append(
            {
                "payload": payload,
                "request_id": request_id,
                "client_host": client_host,
            }
        )
        return PublicContactAcceptedResponse()


@pytest.mark.asyncio
async def test_public_contact_accepts_valid_submission() -> None:
    test_app = _build_test_app()
    service = _RecordingContactService()
    test_app.dependency_overrides[get_public_contact_service] = lambda: service
    test_app.dependency_overrides[get_settings] = lambda: _settings()
    test_app.dependency_overrides[get_redis] = lambda: _FakeRedis()

    transport = ASGITransport(app=test_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/public/contact",
            json={
                "first_name": "Aman",
                "last_name": "Jha",
                "work_email": "aman@example.com",
                "company": "Kairo",
                "hires_per_month": "25",
                "message": "We want to learn more about Kairo for hiring.",
                "website": "",
            },
        )

    test_app.dependency_overrides.clear()

    assert response.status_code == 202
    assert response.json() == {
        "status": "accepted",
        "message": "Thanks — we’ve received your message.",
    }
    assert len(service.calls) == 1
    payload = service.calls[0]["payload"]
    assert isinstance(payload, PublicContactRequest)
    assert payload.work_email == "aman@example.com"


@pytest.mark.asyncio
async def test_public_contact_rejects_invalid_email() -> None:
    test_app = _build_test_app()
    service = _RecordingContactService()
    test_app.dependency_overrides[get_public_contact_service] = lambda: service
    test_app.dependency_overrides[get_redis] = lambda: _FakeRedis()

    transport = ASGITransport(app=test_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/public/contact",
            json={
                "first_name": "Aman",
                "last_name": "Jha",
                "work_email": "not-an-email",
                "company": "Kairo",
                "hires_per_month": "25",
                "message": "We want to learn more about Kairo for hiring.",
                "website": "",
            },
        )

    test_app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert service.calls == []


@pytest.mark.asyncio
async def test_public_contact_rejects_missing_required_fields() -> None:
    test_app = _build_test_app()
    service = _RecordingContactService()
    test_app.dependency_overrides[get_public_contact_service] = lambda: service
    test_app.dependency_overrides[get_redis] = lambda: _FakeRedis()

    transport = ASGITransport(app=test_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/public/contact",
            json={"work_email": "aman@example.com"},
        )

    test_app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert service.calls == []


@pytest.mark.asyncio
async def test_public_contact_rejects_overlong_fields() -> None:
    test_app = _build_test_app()
    service = _RecordingContactService()
    test_app.dependency_overrides[get_public_contact_service] = lambda: service
    test_app.dependency_overrides[get_redis] = lambda: _FakeRedis()

    transport = ASGITransport(app=test_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/public/contact",
            json={
                "first_name": "A" * 81,
                "last_name": "Jha",
                "work_email": "aman@example.com",
                "company": "Kairo",
                "hires_per_month": "25",
                "message": "We want to learn more about Kairo for hiring.",
                "website": "",
            },
        )

    test_app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert service.calls == []


@pytest.mark.asyncio
async def test_public_contact_rate_limits_by_ip() -> None:
    test_app = _build_test_app()
    service = _RecordingContactService()
    redis = _FakeRedis()
    test_app.dependency_overrides[get_public_contact_service] = lambda: service
    test_app.dependency_overrides[get_settings] = lambda: _settings(
        contact_rate_limit_max_requests=1,
        contact_rate_limit_window_seconds=60,
    )
    test_app.dependency_overrides[get_redis] = lambda: redis

    transport = ASGITransport(app=test_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            "/api/v1/public/contact",
            json={
                "first_name": "Aman",
                "last_name": "Jha",
                "work_email": "aman@example.com",
                "company": "Kairo",
                "hires_per_month": "25",
                "message": "We want to learn more about Kairo for hiring.",
                "website": "",
            },
        )
        second = await client.post(
            "/api/v1/public/contact",
            json={
                "first_name": "Aman",
                "last_name": "Jha",
                "work_email": "aman@example.com",
                "company": "Kairo",
                "hires_per_month": "25",
                "message": "We want to learn more about Kairo for hiring.",
                "website": "",
            },
        )

    test_app.dependency_overrides.clear()

    assert first.status_code == 202
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"
    assert "Retry-After" in second.headers
    assert len(service.calls) == 1


@pytest.mark.asyncio
async def test_public_contact_provider_failure_returns_sanitized_503() -> None:
    test_app = _build_test_app()

    class _FailingService:
        async def submit(
            self,
            payload: PublicContactRequest,
            *,
            request_id: str,
            client_host: str | None,
        ):
            raise ServiceUnavailableError("Unable to send email")

    test_app.dependency_overrides[get_public_contact_service] = lambda: _FailingService()
    test_app.dependency_overrides[get_redis] = lambda: _FakeRedis()

    transport = ASGITransport(app=test_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/public/contact",
            json={
                "first_name": "Aman",
                "last_name": "Jha",
                "work_email": "aman@example.com",
                "company": "Kairo",
                "hires_per_month": "25",
                "message": "We want to learn more about Kairo for hiring.",
                "website": "",
            },
        )

    test_app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "service_unavailable",
            "message": "Unable to send email",
        }
    }
