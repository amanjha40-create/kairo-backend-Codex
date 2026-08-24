from __future__ import annotations

import pytest

from app.config import Settings
from app.db.url import build_sync_database_url


def base_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "jwt_secret_key": "test-jwt-secret-key-32-chars-minimum!!",
        "redis_url": "redis://localhost:6379/0",
    }
    values.update(overrides)
    return Settings(**values)


def test_runtime_structured_config_works_without_database_url() -> None:
    settings = base_settings(
        database_host="db.internal",
        database_port=5432,
        database_name="kairo",
        database_user="kairo_app",
        database_password="runtime-secret",
        database_sslmode="require",
    )

    assert settings.runtime_database_url == (
        "postgresql+asyncpg://kairo_app:runtime-secret@db.internal:5432/kairo?sslmode=require"
    )


def test_runtime_structured_config_wins_over_legacy_database_url() -> None:
    settings = base_settings(
        database_url="postgresql+asyncpg://legacy:legacy-secret@legacy-db:5432/kairo?sslmode=require",
        database_host="db.internal",
        database_port=5432,
        database_name="kairo",
        database_user="kairo_app",
        database_password="runtime-secret",
        database_sslmode="verify-full",
    )

    assert settings.runtime_database_url == (
        "postgresql+asyncpg://kairo_app:runtime-secret@db.internal:5432/kairo?sslmode=verify-full"
    )


def test_runtime_partial_structured_config_fails_closed_even_with_legacy_url() -> None:
    with pytest.raises(
        ValueError,
        match="runtime database configuration structured fields are incomplete",
    ):
        base_settings(
            database_url="postgresql+asyncpg://legacy:legacy-secret@legacy-db:5432/kairo?sslmode=require",
            database_host="db.internal",
            database_port=5432,
            database_name="kairo",
            database_user="kairo_app",
            database_password="runtime-secret",
        )


def test_runtime_password_with_special_characters_is_encoded_correctly() -> None:
    settings = base_settings(
        database_host="db.internal",
        database_port=5432,
        database_name="kairo",
        database_user="kairo_app",
        database_password="p@ss:word/with?chars",
        database_sslmode="require",
    )

    assert (
        settings.runtime_database_url
        == "postgresql+asyncpg://kairo_app:p%40ss%3Aword%2Fwith%3Fchars@db.internal:5432/kairo?sslmode=require"
    )


def test_production_shape_accepts_structured_runtime_without_database_url() -> None:
    settings = base_settings(
        app_env="production",
        database_url=None,
        database_host="db.internal",
        database_port=5432,
        database_name="kairo",
        database_user="kairo_app",
        database_password="runtime-secret",
        database_sslmode="require",
        redis_url="rediss://cache.internal:6379/0",
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
        jwt_secret_key="production-jwt-secret-key-that-is-longer-than-forty-eight-characters",
    )

    assert settings.runtime_database_url.endswith("?sslmode=require")


def test_migration_identity_resolves_independently_from_runtime_identity() -> None:
    settings = base_settings(
        database_host="runtime-db.internal",
        database_port=5432,
        database_name="kairo",
        database_user="kairo_app",
        database_password="runtime-secret",
        database_sslmode="require",
        migration_database_host="migration-db.internal",
        migration_database_port=5432,
        migration_database_name="kairo",
        migration_database_user="kairo_migrator",
        migration_database_password="migrator-secret",
        migration_database_sslmode="verify-full",
    )

    assert settings.migration_database_url_effective == (
        "postgresql+asyncpg://kairo_migrator:migrator-secret@migration-db.internal:5432/kairo?sslmode=verify-full"
    )
    assert build_sync_database_url(settings.migration_database_url_effective) == (
        "postgresql+psycopg://kairo_migrator:migrator-secret@migration-db.internal:5432/kairo?sslmode=verify-full"
    )


def test_migration_partial_structured_config_fails_closed() -> None:
    settings = base_settings(
        database_host="runtime-db.internal",
        database_port=5432,
        database_name="kairo",
        database_user="kairo_app",
        database_password="runtime-secret",
        database_sslmode="require",
        migration_database_host="migration-db.internal",
        migration_database_port=5432,
        migration_database_name="kairo",
        migration_database_user="kairo_migrator",
        migration_database_password="migrator-secret",
    )

    with pytest.raises(
        ValueError,
        match="migration database configuration structured fields are incomplete",
    ):
        _ = settings.migration_database_url_effective


def test_migration_resolution_fails_closed_without_migrator_config() -> None:
    settings = base_settings(
        database_host="runtime-db.internal",
        database_port=5432,
        database_name="kairo",
        database_user="kairo_app",
        database_password="runtime-secret",
        database_sslmode="require",
    )

    with pytest.raises(ValueError, match="migration database configuration is required"):
        _ = settings.migration_database_url_effective
