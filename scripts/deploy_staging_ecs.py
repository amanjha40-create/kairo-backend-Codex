#!/usr/bin/env python3
"""Build and deploy an immutable staging image with verified source provenance."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

try:
    from scripts.database_pool_config import database_pool_profile
except ModuleNotFoundError:  # Direct invocation adds scripts/, not the repository root.
    from database_pool_config import database_pool_profile

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
    "import urllib.request; "
    "urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=5)",
]

RUNTIME_TARGETS = {
    "api": {
        "service": "kairo-staging-backend",
        "container": "kairo-staging-backend",
        "command_markers": ("gunicorn", "app.main:app"),
    },
    "worker": {
        "service": "kairo-staging-resume-worker",
        "container": "kairo-staging-resume-worker",
        "command_markers": ("app.workers.sqs_worker",),
    },
}

_DIGEST_IMAGE_PATTERN = re.compile(r"^.+@sha256:[0-9a-f]{64}$")


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
    runtime_kind: str,
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
    pool_profile = database_pool_profile(runtime_kind)
    environment.update(pool_profile.environment())
    container["environment"] = [
        {"name": name, "value": value} for name, value in sorted(environment.items())
    ]
    return payload


def _aws_json(region: str, *arguments: str) -> Any:
    return json.loads(_run(("aws", *arguments, "--region", region, "--output", "json")))


def ensure_staging_target(*, service: str, container: str) -> None:
    if "staging" not in service.lower() or "staging" not in container.lower():
        raise RuntimeError("staging deploy refuses a non-staging service or container")


def validate_runtime_target(
    *,
    runtime_kind: str,
    service_name: str,
    container_name: str,
    service: dict[str, Any],
    task_definition: dict[str, Any],
) -> None:
    """Fail closed before image or ECS mutation when runtime identity is ambiguous."""

    ensure_staging_target(service=service_name, container=container_name)
    expected = RUNTIME_TARGETS[runtime_kind]
    if service_name != expected["service"] or container_name != expected["container"]:
        raise RuntimeError(
            f"{runtime_kind} runtime requires service={expected['service']} "
            f"and container={expected['container']}"
        )
    if service.get("serviceName") != service_name:
        raise RuntimeError("ECS service identity does not match the requested service")
    if task_definition.get("family") != service_name:
        raise RuntimeError("task-definition family does not match the requested service")

    container = next(
        (
            item
            for item in task_definition.get("containerDefinitions", [])
            if item.get("name") == container_name
        ),
        None,
    )
    if container is None:
        raise RuntimeError(f"task definition has no {container_name!r} container")
    command = " ".join(container.get("command") or [])
    if not all(marker in command for marker in expected["command_markers"]):
        raise RuntimeError(f"task-definition command does not match the {runtime_kind} runtime")
    other_kind = "worker" if runtime_kind == "api" else "api"
    if any(marker in command for marker in RUNTIME_TARGETS[other_kind]["command_markers"]):
        raise RuntimeError(f"task-definition command contains {other_kind} runtime markers")


def validate_digest_image_uri(image_uri: str, *, repository_uri: str) -> str:
    if not image_uri.startswith(f"{repository_uri}@") or not _DIGEST_IMAGE_PATTERN.fullmatch(
        image_uri
    ):
        raise RuntimeError("reused image must be a digest-pinned URI in the expected repository")
    return image_uri.removeprefix(f"{repository_uri}@")


def build_and_push_image(
    *,
    repo_root: Path,
    registry: str,
    repository_uri: str,
    source_sha: str,
    build_id: str,
    region: str,
) -> tuple[str, str]:
    tagged_image_uri = f"{repository_uri}:{source_sha}"
    login_password = _run(("aws", "ecr", "get-login-password", "--region", region))
    subprocess.run(
        ("docker", "login", "--username", "AWS", "--password-stdin", registry),
        input=login_password,
        check=True,
        text=True,
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        metadata_path = Path(temp_dir) / "build-metadata.json"
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
                tagged_image_uri,
                "--metadata-file",
                str(metadata_path),
                "--push",
                ".",
            ),
            cwd=repo_root,
            check=True,
        )
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    image_digest = metadata.get("containerimage.digest")
    if not isinstance(image_digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest):
        raise RuntimeError("Docker did not return an immutable image digest")
    return f"{repository_uri}@{image_digest}", image_digest


def deploy(args: argparse.Namespace) -> dict[str, str]:
    repo_root = Path(__file__).resolve().parents[1]
    source_sha = resolve_source_commit(repo_root, args.expected_sha)
    build_id = source_sha
    deployed_at = datetime.now(tz=UTC).isoformat()
    account_id = _aws_json(args.region, "sts", "get-caller-identity")["Account"]
    registry = f"{account_id}.dkr.ecr.{args.region}.amazonaws.com"
    repository_uri = f"{registry}/{args.repository}"

    service_response = _aws_json(
        args.region,
        "ecs",
        "describe-services",
        "--cluster",
        args.cluster,
        "--services",
        args.service,
    )
    services = service_response.get("services", [])
    if len(services) != 1 or service_response.get("failures"):
        raise RuntimeError("ECS did not return exactly one requested service")
    service = services[0]
    task_definition_arn = service["taskDefinition"]
    task_definition = _aws_json(
        args.region,
        "ecs",
        "describe-task-definition",
        "--task-definition",
        task_definition_arn,
    )["taskDefinition"]
    validate_runtime_target(
        runtime_kind=args.runtime_kind,
        service_name=args.service,
        container_name=args.container,
        service=service,
        task_definition=task_definition,
    )

    if args.image_uri:
        image_uri = args.image_uri
        image_digest = validate_digest_image_uri(image_uri, repository_uri=repository_uri)
        image_built = "false"
    else:
        image_uri, image_digest = build_and_push_image(
            repo_root=repo_root,
            registry=registry,
            repository_uri=repository_uri,
            source_sha=source_sha,
            build_id=build_id,
            region=args.region,
        )
        image_built = "true"

    payload = build_task_definition_payload(
        task_definition,
        container_name=args.container,
        image_uri=image_uri,
        source_sha=source_sha,
        build_id=build_id,
        deployed_at=deployed_at,
        runtime_kind=args.runtime_kind,
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
        "image_digest": image_digest,
        "image_built": image_built,
        "task_definition": new_task_definition,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--cluster", default="kairo-production")
    parser.add_argument("--service", required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--repository", default="kairo-backend")
    parser.add_argument("--runtime-kind", choices=("api", "worker"), default="api")
    parser.add_argument("--image-uri")
    return parser.parse_args(argv)


if __name__ == "__main__":
    print(json.dumps(deploy(parse_args()), indent=2))
