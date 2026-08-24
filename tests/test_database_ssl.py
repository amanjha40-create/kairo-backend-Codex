from app.db.url import (
    build_async_database_config,
    build_database_url,
    build_sync_database_url,
    redact_connection_secrets,
)


def test_async_database_config_translates_sslmode_for_asyncpg() -> None:
    url, connect_args = build_async_database_config(
        "postgresql+asyncpg://user:password@db.example/kairo?sslmode=require"
    )

    assert url.render_as_string(hide_password=False) == "postgresql+asyncpg://user:password@db.example/kairo"
    assert connect_args == {"ssl": "require"}


def test_async_database_config_preserves_urls_without_sslmode() -> None:
    database_url = "postgresql+asyncpg://user:password@db.example/kairo?application_name=kairo"

    url, connect_args = build_async_database_config(database_url)

    assert url.render_as_string(hide_password=False) == database_url
    assert connect_args == {}


def test_alembic_database_url_keeps_sslmode_for_psycopg() -> None:
    database_url = "postgresql+asyncpg://user:password@db.example/kairo?sslmode=require"

    assert build_sync_database_url(database_url) == (
        "postgresql+psycopg://user:password@db.example/kairo?sslmode=require"
    )


def test_build_database_url_handles_structured_components() -> None:
    database_url = build_database_url(
        drivername="postgresql+asyncpg",
        username="user",
        password="p@ss:word",
        host="db.example",
        port=5432,
        database="kairo",
        sslmode="require",
    )

    assert database_url.startswith("postgresql+asyncpg://user:")
    assert "@db.example:5432/kairo?sslmode=require" in database_url


def test_redact_connection_secrets_masks_url_passwords() -> None:
    value = (
        "psycopg.OperationalError: connection failed for "
        "postgresql+asyncpg://user:super-secret@db.example:5432/kairo?sslmode=require"
    )

    redacted = redact_connection_secrets(value)

    assert "super-secret" not in redacted
    assert "user:***@" in redacted


def test_redact_connection_secrets_masks_key_value_passwords() -> None:
    value = "password=super-secret database_url=postgresql+asyncpg://user:pw@db.example/kairo"

    redacted = redact_connection_secrets(value)

    assert "super-secret" not in redacted
    assert "password=***" in redacted
    assert "user:***@" in redacted
