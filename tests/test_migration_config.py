"""Alembic must not depend on application integration configuration."""

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from app.db.migration_config import migration_database_url
from app.db.migration_runner import build_migration_config, build_staging_migration_config


def test_staging_binding_enforces_tls_without_mutating_environment():
    env = fields()
    env["MIGRATION_DATABASE_SSLMODE"] = "prefer"
    config = build_staging_migration_config(env)
    assert make_url(config.attributes["migration_database_url"]).query["sslmode"] == "require"
    assert env["MIGRATION_DATABASE_SSLMODE"] == "prefer"


@pytest.mark.parametrize("mode", ["verify-ca", "verify-full"])
def test_staging_binding_preserves_stricter_tls(mode):
    env = fields()
    env["MIGRATION_DATABASE_SSLMODE"] = mode
    config = build_staging_migration_config(env)
    assert make_url(config.attributes["migration_database_url"]).query["sslmode"] == mode


def test_staging_binding_rejects_production():
    env = fields()
    env["APP_ENV"] = "production"
    with pytest.raises(ValueError, match="requires APP_ENV=staging"):
        build_staging_migration_config(env)


@pytest.mark.parametrize("mode", ["require", "verify-ca", "verify-full"])
def test_secure_remote_modes(mode):
    env = fields()
    env["MIGRATION_DATABASE_SSLMODE"] = mode
    assert make_url(migration_database_url(env)).query["sslmode"] == mode


@pytest.mark.parametrize("mode", ["disable", "allow", "prefer", "invalid"])
def test_insecure_remote_modes_rejected(mode):
    env = fields()
    env["MIGRATION_DATABASE_SSLMODE"] = mode
    with pytest.raises(ValueError, match="require TLS"):
        migration_database_url(env)


def test_local_test_can_use_non_tls_database():
    env = fields()
    env.update(
        APP_ENV="test", MIGRATION_DATABASE_HOST="127.0.0.1", MIGRATION_DATABASE_SSLMODE="disable"
    )
    assert make_url(migration_database_url(env)).query["sslmode"] == "disable"


def test_programmatic_config_keeps_script_location_and_url():
    from alembic.script import ScriptDirectory

    config = build_migration_config(fields())
    assert config.config_file_name == "alembic.ini"
    assert config.get_main_option("script_location") == "alembic"
    assert ScriptDirectory.from_config(config).get_heads() == ["097"]
    assert config.attributes["configure_logger"] is False
    assert (
        make_url(config.attributes["migration_database_url"]).password
        == fields()["MIGRATION_DATABASE_PASSWORD"]
    )


def test_programmatic_environment_uses_validated_override_without_runtime_imports():
    root = Path(__file__).resolve().parents[1]
    code = """
import io, sys
from alembic import command
from app.db.migration_runner import build_migration_config
env = {
    'APP_ENV': 'staging', 'MIGRATION_DATABASE_HOST': 'db.example.invalid',
    'MIGRATION_DATABASE_PORT': '5432', 'MIGRATION_DATABASE_NAME': 'synthetic',
    'MIGRATION_DATABASE_USER': 'synthetic', 'MIGRATION_DATABASE_PASSWORD': 'synthetic@:%pass',
    'MIGRATION_DATABASE_SSLMODE': 'require',
}
config = build_migration_config(env)
config.output_buffer = io.StringIO()
command.upgrade(config, '093:094', sql=True)
from app.db.base import Base
assert 'organization_deletion_resolutions' in Base.metadata.tables
assert 'organization_deletion_resolutions' in config.output_buffer.getvalue()
assert 'app.config' not in sys.modules
assert 'app.core.config' not in sys.modules
print('ALEMBIC_CONFIG_PREFLIGHT_PASS')
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        env={"APP_ENV": "staging", "MIGRATION_DATABASE_URL": "invalid-ambient-value"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "ALEMBIC_CONFIG_PREFLIGHT_PASS"


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
