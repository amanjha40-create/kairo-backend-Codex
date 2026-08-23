"""Safety checks for immutable staging deployment provenance."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.deploy_staging_ecs import (
    build_task_definition_payload,
    ensure_staging_target,
    resolve_source_commit,
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


def test_staging_deploy_refuses_non_staging_targets() -> None:
    ensure_staging_target(
        service="kairo-staging-backend",
        container="kairo-staging-backend",
    )

    with pytest.raises(RuntimeError, match="refuses a non-staging"):
        ensure_staging_target(service="kairo-backend", container="kairo-backend")
