"""Alembic must not depend on application integration configuration."""

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from app.db.migration_config import migration_database_url


def fields():
    return {
        "APP_ENV": "staging",
        "MIGRATION_DATABASE_HOST": "db.example.invalid",
        "MIGRATION_DATABASE_PORT": "5432",
        "MIGRATION_DATABASE_NAME": "synthetic",
        "MIGRATION_DATABASE_USER": "migrator",
        "MIGRATION_DATABASE_PASSWORD": "synthetic@:/password",
        "MIGRATION_DATABASE_SSLMODE": "require",
    }


def test_minimal_structured_configuration():
    url = make_url(migration_database_url(fields()))
    assert url.drivername == "postgresql+psycopg"
    assert url.password == "synthetic@:/password"
    assert url.query["sslmode"] == "require"


def test_minimal_url_configuration():
    assert (
        migration_database_url(
            {"MIGRATION_DATABASE_URL": "postgresql+asyncpg://qa:qa@localhost/qa"}
        )
        == "postgresql+psycopg://qa:qa@localhost/qa"
    )


def test_structured_binding_precedes_url():
    env = fields()
    env["MIGRATION_DATABASE_URL"] = "postgresql+psycopg://other:other@other/other"
    assert make_url(migration_database_url(env)).host == "db.example.invalid"


@pytest.mark.parametrize("key", list(fields())[1:])
def test_partial_bindings_fail_closed(key):
    env = fields()
    del env[key]
    with pytest.raises(ValueError, match="Incomplete migration"):
        migration_database_url(env)


def test_runtime_credentials_never_used_as_fallback():
    with pytest.raises(ValueError, match="configuration required"):
        migration_database_url({"DATABASE_URL": "postgresql+psycopg://qa:qa@localhost/qa"})


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_remote_migrations_require_tls(environment):
    with pytest.raises(ValueError, match="require TLS"):
        migration_database_url(
            {
                "APP_ENV": environment,
                "MIGRATION_DATABASE_URL": "postgresql+psycopg://qa:qa@db.invalid/qa",
            }
        )


@pytest.mark.parametrize(
    "value", ["secret-invalid-url", "sqlite:///synthetic", "postgresql+psycopg://"]
)
def test_invalid_url_errors_do_not_expose_input(value):
    with pytest.raises(ValueError) as caught:
        migration_database_url({"MIGRATION_DATABASE_URL": value})
    assert value not in str(caught.value)


def test_alembic_offline_starts_without_application_settings():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "093:094", "--sql"],
        cwd=root,
        env=fields(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "organization_deletion_resolutions" in result.stdout
    assert "JWT_SECRET_KEY" not in result.stderr
