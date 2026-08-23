"""Production settings must fail closed instead of using development fallbacks."""

import pytest
from pydantic import ValidationError

from app.config import Settings


def production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "production",
        "database_url": "postgresql+asyncpg://kairo:secret@db.internal:5432/kairo",
        "redis_url": "rediss://cache.internal:6379/0",
        "jwt_secret_key": "production-jwt-secret-key-that-is-longer-than-forty-eight-characters",
        "email_backend": "smtp",
        "smtp_host": "smtp.internal",
        "phone_otp_enabled": False,
        "app_public_base_url": "https://app.kairoid.com",
        "admin_portal_base_url": "https://admin.kairoid.com",
        "cors_origins": ["https://admin.kairoid.com"],
    }
    values.update(overrides)
    return Settings(**values)


def test_explicit_production_dependencies_are_accepted() -> None:
    settings = production_settings()

    assert settings.app_env == "production"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"database_url": "postgresql+asyncpg://kairo:kairo@localhost:5432/kairo"}, "DATABASE_URL"),
        ({"redis_url": "redis://127.0.0.1:6379/0"}, "REDIS_URL"),
        ({"app_public_base_url": "http://api.kairoid.com"}, "APP_PUBLIC_BASE_URL"),
        ({"admin_portal_base_url": "http://admin.kairoid.com"}, "ADMIN_PORTAL_BASE_URL"),
        ({"cors_origins": []}, "CORS_ORIGINS"),
        ({"cors_origins": ["*"]}, "CORS_ORIGINS"),
        ({"cors_origins": ["https://app.kairoid.com"]}, "ADMIN_PORTAL_BASE_URL"),
        ({"aws_endpoint_url": "http://localstack:4566"}, "AWS_ENDPOINT_URL"),
    ],
)
def test_unsafe_production_fallbacks_are_rejected(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        production_settings(**overrides)
