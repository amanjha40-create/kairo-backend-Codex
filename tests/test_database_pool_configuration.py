"""Focused regression coverage for bounded ECS database pool settings."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import Settings
from app.db.session import engine_options
from scripts.database_pool_config import (
    API_DATABASE_POOL,
    WORKER_DATABASE_POOL,
    DatabasePoolProfile,
    database_pool_profile,
)
from scripts.deploy_staging_ecs import build_task_definition_payload


def _task_definition(environment: str) -> dict[str, object]:
    return {
        "family": f"kairo-{environment}-backend",
        "containerDefinitions": [
            {
                "name": f"kairo-{environment}-backend",
                "image": "example.invalid/kairo-backend:old",
                "environment": [
                    {"name": "APP_ENV", "value": environment},
                    {"name": "DATABASE_POOL_SIZE", "value": "99"},
                    {"name": "DATABASE_MAX_OVERFLOW", "value": "99"},
                    {"name": "DATABASE_POOL_TIMEOUT", "value": "99"},
                ],
            }
        ],
    }


def _environment(payload: dict[str, object]) -> dict[str, str]:
    containers = payload["containerDefinitions"]
    assert isinstance(containers, list)
    container = containers[0]
    assert isinstance(container, dict)
    return {item["name"]: item["value"] for item in container["environment"]}


@pytest.mark.parametrize("environment", ["staging", "production"])
@pytest.mark.parametrize(
    ("runtime_kind", "expected"),
    [("api", API_DATABASE_POOL), ("worker", WORKER_DATABASE_POOL)],
)
def test_deployment_payload_has_explicit_pool_profile(
    environment: str,
    runtime_kind: str,
    expected: DatabasePoolProfile,
) -> None:
    payload = build_task_definition_payload(
        _task_definition(environment),
        container_name=f"kairo-{environment}-backend",
        image_uri="example.invalid/kairo-backend:new",
        source_sha="a" * 40,
        build_id="build-1",
        deployed_at="2026-10-27T00:00:00+00:00",
        runtime_kind=runtime_kind,
    )

    environment_values = _environment(payload)
    assert environment_values["DATABASE_POOL_SIZE"] == str(expected.pool_size)
    assert environment_values["DATABASE_MAX_OVERFLOW"] == str(expected.max_overflow)
    assert environment_values["DATABASE_POOL_TIMEOUT"] == str(
        expected.pool_timeout_seconds
    )


def test_environment_overrides_source_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_POOL_SIZE", "4")
    monkeypatch.setenv("DATABASE_MAX_OVERFLOW", "2")
    monkeypatch.setenv("DATABASE_POOL_TIMEOUT", "10")

    settings = Settings(app_env="test", _env_file=None)

    assert settings.database_pool_size == 4
    assert settings.database_max_overflow == 2
    assert settings.database_pool_timeout == 10


@pytest.mark.parametrize(
    ("profile", "process_count", "expected_ceiling"),
    [(API_DATABASE_POOL, 2, 12), (WORKER_DATABASE_POOL, 1, 4)],
)
def test_connection_ceiling_does_not_multiply_unexpectedly(
    profile: DatabasePoolProfile,
    process_count: int,
    expected_ceiling: int,
) -> None:
    assert profile.connection_ceiling(process_count=process_count) == expected_ceiling


def test_engine_receives_explicit_runtime_pool_values() -> None:
    settings = SimpleNamespace(
        app_env="production",
        database_pool_size=4,
        database_max_overflow=2,
        database_pool_timeout=10.0,
    )

    options = engine_options(settings, connect_args={"ssl": "required"}, echo_sql=False)

    assert options["pool_size"] == 4
    assert options["max_overflow"] == 2
    assert options["pool_timeout"] == 10.0


def test_invalid_process_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one"):
        API_DATABASE_POOL.connection_ceiling(process_count=0)


def test_invalid_runtime_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported runtime kind"):
        database_pool_profile("web")
