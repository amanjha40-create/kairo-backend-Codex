"""Security regression tests for production health-probe host handling."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.v1.routes.health as health_module
import app.main as main_module
import app.middleware.request_context as request_context_module
from app.config import Settings


def _production_settings() -> Settings:
    return Settings(
        app_env="production",
        database_url=(
            "postgresql+asyncpg://kairo:secret@db.internal:5432/kairo?ssl=require"
        ),
        redis_url="rediss://cache.internal:6379/0",
        jwt_secret_key="production-jwt-secret-key-that-is-longer-than-forty-eight-characters",
        email_backend="smtp",
        smtp_host="smtp.internal",
        phone_otp_enabled=True,
        phone_otp_backend="sns",
        aws_region="us-east-1",
        app_public_base_url="https://api.kairoid.com",
        admin_portal_base_url="https://admin.kairoid.com",
        cors_origins=["https://admin.kairoid.com"],
        docs_enabled=False,
        job_backend="sqs",
        sqs_main_queue_url="https://sqs.us-east-1.amazonaws.com/123456789012/kairo-main",
        app_git_sha="a" * 40,
        app_build_id="a" * 40,
        app_deployed_at="2026-08-23T12:00:00+00:00",
        trusted_hosts=["api.kairoid.com"],
    )


@pytest.fixture
def production_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    settings = _production_settings()

    async def dependency_available(*_: object) -> bool:
        return True

    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(request_context_module, "get_settings", lambda: settings)
    monkeypatch.setattr(health_module, "get_settings", lambda: settings)
    monkeypatch.setattr(health_module, "ping_database", dependency_available)
    monkeypatch.setattr(health_module, "ping_redis", dependency_available)
    return main_module.create_app()


def _request(
    application: FastAPI,
    method: str,
    path: str,
    *,
    local_address: str,
    host: str | None = None,
):
    with TestClient(application, base_url=f"http://{local_address}") as client:
        return client.request(method, path, headers={"Host": host or local_address})


@pytest.mark.parametrize(
    ("path", "local_address"),
    [
        ("/api/v1/health/live", "127.0.0.1"),
        ("/api/v1/health/ready", "127.0.0.1"),
        ("/api/v1/health/ready", "172.31.29.66"),
    ],
)
def test_internal_health_probe_hosts_are_accepted(
    production_app: FastAPI,
    path: str,
    local_address: str,
) -> None:
    response = _request(
        production_app,
        "GET",
        path,
        local_address=local_address,
    )

    assert response.status_code == 200


def test_head_health_probe_bypasses_host_check(production_app: FastAPI) -> None:
    response = _request(
        production_app,
        "HEAD",
        "/api/v1/health/live",
        local_address="127.0.0.1",
    )

    assert response.status_code != 400


@pytest.mark.parametrize(
    ("method", "path", "local_address", "host"),
    [
        ("GET", "/api/v1/admin/session", "127.0.0.1", None),
        ("GET", "/api/v1/auth/login", "127.0.0.1", "malicious.example"),
        ("GET", "/api/v1/health/ready/foo", "127.0.0.1", None),
        ("POST", "/api/v1/health/ready", "127.0.0.1", None),
        ("GET", "/api/v1/health/live", "127.0.0.1", "malicious.example"),
        ("GET", "/api/v1/health/ready", "172.31.29.66", "172.31.29.67"),
        ("GET", "/", "127.0.0.1", "malicious.example"),
    ],
)
def test_trusted_host_enforcement_remains_outside_local_health_probes(
    production_app: FastAPI,
    method: str,
    path: str,
    local_address: str,
    host: str | None,
) -> None:
    response = _request(
        production_app,
        method,
        path,
        local_address=local_address,
        host=host,
    )

    assert response.status_code == 400
    assert response.text == "Invalid host header"


def test_normal_production_host_is_accepted(production_app: FastAPI) -> None:
    response = _request(
        production_app,
        "GET",
        "/api/v1/admin/session",
        local_address="127.0.0.1",
        host="api.kairoid.com",
    )

    assert response.status_code == 401
