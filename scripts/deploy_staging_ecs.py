#!/usr/bin/env python3
"""Build and deploy an immutable staging image with verified source provenance."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

TASK_DEFINITION_FIELDS = (
    "family",
    "taskRoleArn",
    "executionRoleArn",
    "networkMode",
    "containerDefinitions",
    "volumes",
    "placementConstraints",
    "requiresCompatibilities",
    "cpu",
    "memory",
    "pidMode",
    "ipcMode",
    "proxyConfiguration",
    "inferenceAccelerators",
    "ephemeralStorage",
    "runtimePlatform",
)

RUNTIME_HEALTHCHECK_COMMAND = [
    "CMD",
    "python",
    "-c",
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=5)",
]


def _run(command: Sequence[str], *, cwd: Path | None = None) -> str:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def resolve_source_commit(repo_root: Path, expected_sha: str | None = None) -> str:
    if _run(("git", "status", "--porcelain"), cwd=repo_root):
        raise RuntimeError("staging deploy requires a clean Git checkout")
    source_sha = _run(("git", "rev-parse", "HEAD"), cwd=repo_root)
    _run(("git", "cat-file", "-e", f"{source_sha}^{{commit}}"), cwd=repo_root)
    if len(source_sha) != 40:
        raise RuntimeError("Git did not return a full 40-character source commit")
    if expected_sha is not None and source_sha != expected_sha:
        raise RuntimeError(
            f"source commit mismatch: checkout is {source_sha}, expected {expected_sha}"
        )
    return source_sha


def build_task_definition_payload(
    task_definition: dict[str, Any],
    *,
    container_name: str,
    image_uri: str,
    source_sha: str,
    build_id: str,
    deployed_at: str,
) -> dict[str, Any]:
    payload = {
        field: task_definition[field]
        for field in TASK_DEFINITION_FIELDS
        if field in task_definition
    }
    containers = payload.get("containerDefinitions", [])
    container = next(
        (item for item in containers if item.get("name") == container_name),
        None,
    )
    if container is None:
        raise RuntimeError(f"task definition has no {container_name!r} container")

    container["image"] = image_uri
    health_check = dict(container.get("healthCheck") or {})
    if health_check:
        health_check["command"] = list(RUNTIME_HEALTHCHECK_COMMAND)
        container["healthCheck"] = health_check
    environment = {
        item["name"]: item["value"]
        for item in container.get("environment", [])
        if "name" in item and "value" in item
    }
    environment.update(
        {
            "APP_GIT_SHA": source_sha,
            "APP_BUILD_ID": build_id,
            "APP_VERSION": f"git-{source_sha[:12]}",
            "APP_DEPLOYED_AT": deployed_at,
        }
    )
    container["environment"] = [
        {"name": name, "value": value} for name, value in sorted(environment.items())
    ]
    return payload


def _aws_json(region: str, *arguments: str) -> Any:
    return json.loads(_run(("aws", *arguments, "--region", region, "--output", "json")))


def ensure_staging_target(*, service: str, container: str) -> None:
    if "staging" not in service.lower() or "staging" not in container.lower():
        raise RuntimeError("staging deploy refuses a non-staging service or container")


def deploy(args: argparse.Namespace) -> dict[str, str]:
    repo_root = Path(__file__).resolve().parents[1]
    ensure_staging_target(service=args.service, container=args.container)
    source_sha = resolve_source_commit(repo_root, args.expected_sha)
    build_id = source_sha
    deployed_at = datetime.now(tz=UTC).isoformat()
    account_id = _aws_json(args.region, "sts", "get-caller-identity")["Account"]
    registry = f"{account_id}.dkr.ecr.{args.region}.amazonaws.com"
    image_uri = f"{registry}/{args.repository}:{source_sha}"

    login_password = _run(("aws", "ecr", "get-login-password", "--region", args.region))
    subprocess.run(
        ("docker", "login", "--username", "AWS", "--password-stdin", registry),
        input=login_password,
        check=True,
        text=True,
    )
    subprocess.run(
        (
            "docker",
            "buildx",
            "build",
            "--platform",
            "linux/arm64",
            "--build-arg",
            f"APP_GIT_SHA={source_sha}",
            "--build-arg",
            f"APP_BUILD_ID={build_id}",
            "--label",
            f"org.opencontainers.image.revision={source_sha}",
            "--tag",
            image_uri,
            "--push",
            ".",
        ),
        cwd=repo_root,
        check=True,
    )

    service = _aws_json(
        args.region,
        "ecs",
        "describe-services",
        "--cluster",
        args.cluster,
        "--services",
        args.service,
    )["services"][0]
    task_definition_arn = service["taskDefinition"]
    task_definition = _aws_json(
        args.region,
        "ecs",
        "describe-task-definition",
        "--task-definition",
        task_definition_arn,
    )["taskDefinition"]
    payload = build_task_definition_payload(
        task_definition,
        container_name=args.container,
        image_uri=image_uri,
        source_sha=source_sha,
        build_id=build_id,
        deployed_at=deployed_at,
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as payload_file:
        json.dump(payload, payload_file)
        payload_file.flush()
        registered = _aws_json(
            args.region,
            "ecs",
            "register-task-definition",
            "--cli-input-json",
            f"file://{payload_file.name}",
        )["taskDefinition"]

    new_task_definition = registered["taskDefinitionArn"]
    _aws_json(
        args.region,
        "ecs",
        "update-service",
        "--cluster",
        args.cluster,
        "--service",
        args.service,
        "--task-definition",
        new_task_definition,
    )
    subprocess.run(
        (
            "aws",
            "ecs",
            "wait",
            "services-stable",
            "--cluster",
            args.cluster,
            "--services",
            args.service,
            "--region",
            args.region,
        ),
        check=True,
    )
    return {
        "source_sha": source_sha,
        "build_id": build_id,
        "image_uri": image_uri,
        "task_definition": new_task_definition,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--cluster", default="kairo-production")
    parser.add_argument("--service", default="kairo-staging-backend")
    parser.add_argument("--container", default="kairo-staging-backend")
    parser.add_argument("--repository", default="kairo-backend")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(deploy(parse_args()), indent=2))
