"""Production settings must fail closed instead of using development fallbacks."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.main as main_module
import app.middleware.request_context as request_context_module
from app.config import Settings


def production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "production",
        "database_url": "postgresql+asyncpg://kairo:secret@db.internal:5432/kairo?ssl=require",
        "redis_url": "rediss://cache.internal:6379/0",
        "jwt_secret_key": "production-jwt-secret-key-that-is-longer-than-forty-eight-characters",
        "email_backend": "smtp",
        "smtp_host": "smtp.internal",
        "phone_otp_enabled": True,
        "phone_otp_backend": "sns",
        "aws_region": "us-east-1",
        "app_public_base_url": "https://api.kairoid.com",
        "institution_portal_base_url": "https://institution.kairoid.com",
        "admin_portal_base_url": "https://admin.kairoid.com",
        "cors_origins": ["https://admin.kairoid.com"],
        "docs_enabled": False,
        "job_backend": "sqs",
        "sqs_main_queue_url": "https://sqs.us-east-1.amazonaws.com/123456789012/kairo-main",
        "app_git_sha": "a" * 40,
        "app_build_id": "a" * 40,
        "app_deployed_at": "2026-08-23T12:00:00+00:00",
        "trusted_hosts": ["api.kairoid.com"],
    }
    values.update(overrides)
    return Settings(**values)


def test_explicit_production_dependencies_are_accepted() -> None:
    settings = production_settings()

    assert settings.app_env == "production"
    assert settings.runtime_database_url.startswith("postgresql+asyncpg://")


def test_structured_runtime_database_configuration_is_accepted() -> None:
    settings = production_settings(
        database_url=None,
        database_host="db.internal",
        database_port=5432,
        database_name="kairo",
        database_user="kairo_app",
        database_password="structured-secret",
        database_sslmode="require",
    )

    assert "kairo_app" in settings.runtime_database_url
    assert "@db.internal:5432/kairo?sslmode=require" in settings.runtime_database_url


def test_structured_runtime_database_configuration_wins_over_legacy_url() -> None:
    settings = production_settings(
        database_host="db.internal",
        database_port=5432,
        database_name="kairo",
        database_user="kairo_app",
        database_password="structured-secret",
        database_sslmode="require",
    )

    assert "kairo_app" in settings.runtime_database_url
    assert "structured-secret" in settings.runtime_database_url
    assert "kairo:secret" not in settings.runtime_database_url


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"database_url": "postgresql+asyncpg://kairo:kairo@localhost:5432/kairo"}, "DATABASE_URL"),
        (
            {"database_url": "postgresql+asyncpg://kairo:secret@db.internal:5432/kairo"},
            "DATABASE_URL",
        ),
        ({"redis_url": "redis://127.0.0.1:6379/0"}, "REDIS_URL"),
        ({"redis_url": "redis://cache.internal:6379/0"}, "REDIS_URL"),
        ({"app_public_base_url": "http://api.kairoid.com"}, "APP_PUBLIC_BASE_URL"),
        (
            {"institution_portal_base_url": "http://institution.kairoid.com"},
            "INSTITUTION_PORTAL_BASE_URL",
        ),
        ({"admin_portal_base_url": "http://admin.kairoid.com"}, "ADMIN_PORTAL_BASE_URL"),
        ({"cors_origins": []}, "CORS_ORIGINS"),
        ({"cors_origins": ["*"]}, "CORS_ORIGINS"),
        ({"cors_origins": ["https://app.kairoid.com"]}, "ADMIN_PORTAL_BASE_URL"),
        ({"aws_endpoint_url": "http://localstack:4566"}, "AWS_ENDPOINT_URL"),
        ({"controlled_testing": True}, "CONTROLLED_TESTING"),
        (
            {"phone_otp_backend": "staging_fixed", "staging_phone_otp_code": "123456"},
            "Staging fixed OTP",
        ),
        ({"docs_enabled": True}, "DOCS_ENABLED"),
        ({"database_echo_sql": True}, "DATABASE_ECHO_SQL"),
        ({"log_level": "DEBUG"}, "LOG_LEVEL"),
        ({"email_dev_log_secrets": True}, "EMAIL_DEV_LOG_SECRETS"),
        (
            {
                "database_url": None,
                "database_host": "db.internal",
                "database_port": 5432,
                "database_name": "kairo",
                "database_user": "kairo_app",
            },
            "structured fields are incomplete",
        ),
        ({"job_backend": "inline"}, "JOB_BACKEND"),
        ({"sqs_main_queue_url": None}, "SQS_MAIN_QUEUE_URL"),
        ({"app_git_sha": "short"}, "APP_GIT_SHA"),
        ({"app_build_id": None}, "APP_BUILD_ID"),
        ({"app_deployed_at": None}, "APP_DEPLOYED_AT"),
        ({"app_deployed_at": "not-a-date"}, "APP_DEPLOYED_AT"),
        ({"trusted_hosts": []}, "TRUSTED_HOSTS"),
        ({"cors_origins": ["http://admin.kairoid.com"]}, "CORS_ORIGINS"),
        ({"cors_origins": ["https://admin.kairoid.com/path"]}, "CORS_ORIGINS"),
    ],
)
def test_unsafe_production_fallbacks_are_rejected(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        production_settings(**overrides)


def test_production_cors_allows_admin_origin_and_rejects_unapproved_origin(monkeypatch) -> None:
    settings = production_settings()
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(request_context_module, "get_settings", lambda: settings)

    with TestClient(main_module.create_app()) as client:
        approved = client.options(
            "/api/v1/admin/session",
            headers={
                "Origin": "https://admin.kairoid.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        rejected = client.options(
            "/api/v1/admin/session",
            headers={
                "Origin": "https://unapproved.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert approved.status_code == 200
    assert approved.headers["access-control-allow-origin"] == "https://admin.kairoid.com"
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers


def test_sensitive_admin_responses_receive_security_and_no_store_headers(monkeypatch) -> None:
    settings = production_settings()
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(request_context_module, "get_settings", lambda: settings)

    with TestClient(main_module.create_app()) as client:
        response = client.get("/api/v1/admin/session", headers={"Host": "api.kairoid.com"})

    assert response.status_code == 401
    assert response.headers["cache-control"] == "private, no-store, max-age=0, must-revalidate"
    assert response.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["content-security-policy"] == (
        "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
    )
