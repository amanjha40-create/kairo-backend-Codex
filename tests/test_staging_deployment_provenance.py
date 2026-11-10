"""Safety checks for immutable staging deployment provenance."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.deploy_staging_ecs import (
    build_task_definition_payload,
    ensure_staging_target,
    parse_args,
    resolve_source_commit,
    validate_digest_image_uri,
    validate_runtime_target,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_resolve_source_commit_requires_exact_clean_head(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "admin8@example.invalid")
    _git(tmp_path, "config", "user.name", "ADMIN-8 Test")
    (tmp_path / "tracked.txt").write_text("canonical\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "-m", "test: canonical source")
    source_sha = _git(tmp_path, "rev-parse", "HEAD")

    assert resolve_source_commit(tmp_path, source_sha) == source_sha
    with pytest.raises(RuntimeError, match="source commit mismatch"):
        resolve_source_commit(tmp_path, "0" * 40)

    (tmp_path / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="clean Git checkout"):
        resolve_source_commit(tmp_path, source_sha)


def test_task_definition_provenance_replaces_stale_values() -> None:
    source_sha = "a" * 40
    task_definition = {
        "family": "kairo-staging-backend",
        "revision": 143,
        "taskDefinitionArn": "stale-arn",
        "containerDefinitions": [
            {
                "name": "kairo-staging-backend",
                "image": "example.invalid/kairo-backend:stale",
                "environment": [
                    {"name": "APP_GIT_SHA", "value": "mistyped"},
                    {"name": "APP_BUILD_ID", "value": "stale"},
                    {"name": "APP_ENV", "value": "staging"},
                ],
            }
        ],
    }

    payload = build_task_definition_payload(
        task_definition,
        container_name="kairo-staging-backend",
        image_uri=f"example.invalid/kairo-backend:{source_sha}",
        source_sha=source_sha,
        build_id=source_sha,
        deployed_at="2026-08-23T10:00:00+00:00",
        runtime_kind="api",
    )

    assert "revision" not in payload
    assert "taskDefinitionArn" not in payload
    container = payload["containerDefinitions"][0]
    assert container["image"].endswith(source_sha)
    environment = {item["name"]: item["value"] for item in container["environment"]}
    assert environment["APP_GIT_SHA"] == source_sha
    assert environment["APP_BUILD_ID"] == source_sha
    assert environment["APP_VERSION"] == f"git-{source_sha[:12]}"
    assert environment["APP_ENV"] == "staging"
    assert environment["DATABASE_POOL_SIZE"] == "4"
    assert environment["DATABASE_MAX_OVERFLOW"] == "2"
    assert environment["DATABASE_POOL_TIMEOUT"] == "10"


def test_staging_deploy_refuses_non_staging_targets() -> None:
    ensure_staging_target(
        service="kairo-staging-backend",
        container="kairo-staging-backend",
    )

    with pytest.raises(RuntimeError, match="refuses a non-staging"):
        ensure_staging_target(service="kairo-backend", container="kairo-backend")


def _runtime_task_definition(runtime_kind: str) -> dict[str, object]:
    if runtime_kind == "api":
        service = "kairo-staging-backend"
        command = ["/bin/sh", "-c", "exec gunicorn app.main:app"]
    else:
        service = "kairo-staging-resume-worker"
        command = ["/bin/sh", "-c", "exec python -m app.workers.sqs_worker"]
    return {
        "family": service,
        "containerDefinitions": [{"name": service, "command": command}],
    }


@pytest.mark.parametrize("runtime_kind", ["api", "worker"])
def test_runtime_target_requires_exact_service_container_and_command(runtime_kind: str) -> None:
    task_definition = _runtime_task_definition(runtime_kind)
    service_name = str(task_definition["family"])
    validate_runtime_target(
        runtime_kind=runtime_kind,
        service_name=service_name,
        container_name=service_name,
        service={"serviceName": service_name},
        task_definition=task_definition,
    )


def test_worker_settings_are_rejected_for_api_service_before_mutation() -> None:
    with pytest.raises(RuntimeError, match="worker runtime requires"):
        validate_runtime_target(
            runtime_kind="worker",
            service_name="kairo-staging-backend",
            container_name="kairo-staging-backend",
            service={"serviceName": "kairo-staging-backend"},
            task_definition=_runtime_task_definition("api"),
        )


def test_runtime_command_must_match_requested_identity() -> None:
    task_definition = _runtime_task_definition("worker")
    task_definition["family"] = "kairo-staging-backend"
    task_definition["containerDefinitions"][0]["name"] = "kairo-staging-backend"
    with pytest.raises(RuntimeError, match="command does not match"):
        validate_runtime_target(
            runtime_kind="api",
            service_name="kairo-staging-backend",
            container_name="kairo-staging-backend",
            service={"serviceName": "kairo-staging-backend"},
            task_definition=task_definition,
        )


def test_reused_image_must_be_digest_pinned_in_expected_repository() -> None:
    repository = "123.dkr.ecr.us-east-1.amazonaws.com/kairo-backend"
    digest = f"sha256:{'a' * 64}"
    assert validate_digest_image_uri(f"{repository}@{digest}", repository_uri=repository) == digest
    with pytest.raises(RuntimeError, match="digest-pinned"):
        validate_digest_image_uri(f"{repository}:latest", repository_uri=repository)


def test_service_and_container_arguments_are_mandatory() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--expected-sha", "a" * 40])


def test_one_digest_preserves_api_and_worker_entrypoints() -> None:
    image_uri = f"example.invalid/kairo-backend@sha256:{'b' * 64}"
    api = build_task_definition_payload(
        _runtime_task_definition("api"),
        container_name="kairo-staging-backend",
        image_uri=image_uri,
        source_sha="a" * 40,
        build_id="build-1",
        deployed_at="2026-11-10T00:00:00+00:00",
        runtime_kind="api",
    )
    worker = build_task_definition_payload(
        _runtime_task_definition("worker"),
        container_name="kairo-staging-resume-worker",
        image_uri=image_uri,
        source_sha="a" * 40,
        build_id="build-1",
        deployed_at="2026-11-10T00:00:00+00:00",
        runtime_kind="worker",
    )

    api_container = api["containerDefinitions"][0]
    worker_container = worker["containerDefinitions"][0]
    assert api_container["image"] == worker_container["image"] == image_uri
    assert "app.main:app" in " ".join(api_container["command"])
    assert "app.workers.sqs_worker" in " ".join(worker_container["command"])
