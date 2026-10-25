"""Exact-ID clean-slate planner; execution is gated and disabled by default."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
from sqlalchemy import text

from app.services.clean_slate_orchestrator import (
    BackupEvidence,
    CleanSlateAllowlist,
    CleanSlateOrchestrator,
    CleanSlateSafetyError,
    verify_artifact_checksum,
)

_ALLOWLIST_KEYS = {
    "schema_version",
    "environment",
    "approved_user_ids",
    "approved_pending_signup_ids",
    "approved_organization_ids",
    "approved_storage_object_ids",
    "protected_user_ids",
    "backup_evidence",
}
_BACKUP_KEYS = {
    "rds_snapshot_id",
    "rds_database_id",
    "rds_snapshot_created_at",
    "s3_backup_uri",
    "s3_backup_sha256",
}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--allowlist", type=Path, required=True)
    result.add_argument("--allowlist-sha256", required=True)
    result.add_argument("--execute", action="store_true")
    result.add_argument("--confirm-environment")
    result.add_argument("--confirm-production-clean-slate", action="store_true")
    result.add_argument("--progress-file", type=Path)
    result.add_argument("--progress-s3-uri")
    result.add_argument("--ecs-cluster")
    result.add_argument("--api-service")
    result.add_argument("--worker-service")
    result.add_argument("--live-url")
    result.add_argument("--ready-url")
    result.add_argument("--overdue-alarm")
    return result


def _uuid_set(values: Any, field: str) -> frozenset[UUID]:
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise CleanSlateSafetyError(f"invalid_{field}")
    try:
        parsed = frozenset(UUID(value) for value in values)
    except ValueError as error:
        raise CleanSlateSafetyError(f"invalid_{field}") from error
    if len(parsed) != len(values):
        raise CleanSlateSafetyError(f"duplicate_{field}")
    return parsed


def load_allowlist(payload: bytes) -> CleanSlateAllowlist:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CleanSlateSafetyError("invalid_allowlist_json") from error
    if not isinstance(value, dict) or set(value) != _ALLOWLIST_KEYS:
        raise CleanSlateSafetyError("invalid_allowlist_schema")
    if not isinstance(value["schema_version"], int) or not isinstance(
        value["environment"], str
    ):
        raise CleanSlateSafetyError("invalid_allowlist_schema")
    storage = value["approved_storage_object_ids"]
    if not isinstance(storage, list) or any(
        not isinstance(item, str) or len(item) != 64 for item in storage
    ):
        raise CleanSlateSafetyError("invalid_storage_allowlist")
    if len(set(storage)) != len(storage):
        raise CleanSlateSafetyError("duplicate_storage_allowlist")
    backup_value = value["backup_evidence"]
    backup = None
    if backup_value is not None:
        if not isinstance(backup_value, dict) or set(backup_value) != _BACKUP_KEYS:
            raise CleanSlateSafetyError("invalid_backup_evidence")
        if any(not isinstance(backup_value[key], str) for key in _BACKUP_KEYS):
            raise CleanSlateSafetyError("invalid_backup_evidence")
        backup = BackupEvidence(**backup_value)
    return CleanSlateAllowlist(
        schema_version=value["schema_version"],
        environment=value["environment"],
        approved_user_ids=_uuid_set(value["approved_user_ids"], "approved_user_ids"),
        approved_pending_signup_ids=_uuid_set(
            value["approved_pending_signup_ids"], "approved_pending_signup_ids"
        ),
        approved_organization_ids=_uuid_set(
            value["approved_organization_ids"], "approved_organization_ids"
        ),
        approved_storage_object_ids=frozenset(storage),
        protected_user_ids=_uuid_set(value["protected_user_ids"], "protected_user_ids"),
        backup_evidence=backup,
    )


def _parse_s3_uri(value: str) -> tuple[str, str]:
    parsed = urlparse(value)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise CleanSlateSafetyError("invalid_s3_uri")
    return parsed.netloc, parsed.path.lstrip("/")


class AwsBackupGate:
    def __init__(self, settings: Any) -> None:
        import boto3

        session = boto3.session.Session(region_name=settings.aws_region)
        self._rds = session.client("rds")
        self._s3 = session.client("s3")

    async def verify(self, evidence: BackupEvidence) -> None:
        if not evidence.complete():
            raise CleanSlateSafetyError("production_backup_evidence_missing")

        def verify_sync() -> None:
            response = self._rds.describe_db_snapshots(
                DBSnapshotIdentifier=evidence.rds_snapshot_id
            )
            snapshots = response.get("DBSnapshots", [])
            if len(snapshots) != 1:
                raise CleanSlateSafetyError("rds_snapshot_not_found")
            snapshot = snapshots[0]
            if (
                snapshot.get("Status") != "available"
                or snapshot.get("DBInstanceIdentifier") != evidence.rds_database_id
                or snapshot.get("SnapshotCreateTime") is None
                or snapshot["SnapshotCreateTime"].isoformat()
                != evidence.rds_snapshot_created_at
            ):
                raise CleanSlateSafetyError("rds_snapshot_not_restorable")
            bucket, key = _parse_s3_uri(evidence.s3_backup_uri)
            body = self._s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            verify_artifact_checksum(body, evidence.s3_backup_sha256)

        await asyncio.to_thread(verify_sync)


class AwsHealthGate:
    def __init__(self, settings: Any, args: argparse.Namespace) -> None:
        import boto3

        required = (
            args.ecs_cluster,
            args.api_service,
            args.worker_service,
            args.live_url,
            args.ready_url,
            args.overdue_alarm,
            settings.sqs_main_queue_url,
            settings.sqs_dlq_url,
        )
        if any(not value for value in required):
            raise CleanSlateSafetyError("health_gate_configuration_missing")
        session = boto3.session.Session(region_name=settings.aws_region)
        self._ecs = session.client("ecs")
        self._sqs = session.client("sqs")
        self._cloudwatch = session.client("cloudwatch")
        self._settings = settings
        self._args = args

    async def __call__(self) -> None:
        await asyncio.gather(self._check_aws(), self._check_http())

    async def _check_aws(self) -> None:
        def check_sync() -> None:
            response = self._ecs.describe_services(
                cluster=self._args.ecs_cluster,
                services=[self._args.api_service, self._args.worker_service],
            )
            services = response.get("services", [])
            if len(services) != 2:
                raise CleanSlateSafetyError("ecs_service_health_failed")
            for service in services:
                deployments = service.get("deployments", [])
                primary = [item for item in deployments if item.get("status") == "PRIMARY"]
                if (
                    service.get("desiredCount") != 1
                    or service.get("runningCount") != 1
                    or service.get("pendingCount") != 0
                    or len(primary) != 1
                    or primary[0].get("rolloutState") != "COMPLETED"
                ):
                    raise CleanSlateSafetyError("ecs_service_health_failed")
            for queue_url in (
                self._settings.sqs_main_queue_url,
                self._settings.sqs_dlq_url,
            ):
                attributes = self._sqs.get_queue_attributes(
                    QueueUrl=queue_url,
                    AttributeNames=[
                        "ApproximateNumberOfMessages",
                        "ApproximateNumberOfMessagesNotVisible",
                        "ApproximateNumberOfMessagesDelayed",
                    ],
                )["Attributes"]
                if any(int(attributes.get(name, "0")) for name in attributes):
                    raise CleanSlateSafetyError("queue_health_failed")
            alarms = self._cloudwatch.describe_alarms(
                AlarmNames=[self._args.overdue_alarm]
            ).get("MetricAlarms", [])
            if len(alarms) != 1 or alarms[0].get("StateValue") != "OK":
                raise CleanSlateSafetyError("overdue_alarm_not_ok")

        await asyncio.to_thread(check_sync)

    async def _check_http(self) -> None:
        async with httpx.AsyncClient(follow_redirects=False, timeout=10) as client:
            for url in (self._args.live_url, self._args.ready_url):
                response = await client.get(url)
                if response.status_code != 200:
                    raise CleanSlateSafetyError("api_health_failed")


class ProgressStore:
    def __init__(
        self,
        *,
        artifact_sha256: str,
        local_path: Path | None,
        s3_uri: str | None,
        settings: Any,
    ) -> None:
        self._artifact_sha256 = artifact_sha256
        self._local_path = local_path
        self._s3_uri = s3_uri
        self._settings = settings
        self._events: list[dict[str, object]] = []
        self._load_existing()

    @property
    def completed_user_ids(self) -> frozenset[UUID]:
        return frozenset(
            UUID(str(event["user_id"]))
            for event in self._events
            if event.get("event") == "clean_slate_user_committed"
            and isinstance(event.get("user_id"), str)
        )

    def _load_existing(self) -> None:
        payload = None
        if self._local_path and self._local_path.exists():
            payload = self._local_path.read_bytes()
        elif self._s3_uri:
            payload = self._read_s3()
        if payload is None:
            return
        try:
            value = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CleanSlateSafetyError("invalid_progress_artifact") from error
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != 1
            or value.get("allowlist_sha256") != self._artifact_sha256
            or not isinstance(value.get("events"), list)
            or any(not isinstance(event, dict) for event in value["events"])
        ):
            raise CleanSlateSafetyError("progress_artifact_mismatch")
        self._events = value["events"]

    def record(self, event: dict[str, object]) -> None:
        self._events.append(event)
        payload = json.dumps(
            {
                "schema_version": 1,
                "allowlist_sha256": self._artifact_sha256,
                "events": self._events,
            },
            sort_keys=True,
        ).encode()
        if self._local_path:
            self._write_local(payload)
        if self._s3_uri:
            self._write_s3(payload)

    def _write_local(self, payload: bytes) -> None:
        path = self._local_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)

    def _write_s3(self, payload: bytes) -> None:
        import boto3

        bucket, key = _parse_s3_uri(self._s3_uri or "")
        client = boto3.session.Session(region_name=self._settings.aws_region).client("s3")
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=payload,
            ContentType="application/json",
            Metadata={"allowlist-sha256": self._artifact_sha256},
        )

    def _read_s3(self) -> bytes | None:
        import boto3
        from botocore.exceptions import ClientError

        bucket, key = _parse_s3_uri(self._s3_uri or "")
        client = boto3.session.Session(region_name=self._settings.aws_region).client("s3")
        try:
            return client.get_object(Bucket=bucket, Key=key)["Body"].read()
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                return None
            raise


async def run(args: argparse.Namespace) -> dict[str, object]:
    from redis.asyncio import Redis

    from app.config import get_settings
    from app.db.session import async_session_factory, engine

    settings = get_settings()
    payload = args.allowlist.read_bytes()
    verify_artifact_checksum(payload, args.allowlist_sha256)
    allowlist = load_allowlist(payload)
    if allowlist.environment != settings.app_env.value:
        raise CleanSlateSafetyError("allowlist_environment_mismatch")
    if engine.echo:
        raise CleanSlateSafetyError("sql_echo_must_be_disabled")
    try:
        async with Redis.from_url(settings.redis_url) as redis:
            async with async_session_factory() as session:
                orchestrator = CleanSlateOrchestrator(session, settings, redis)
                if not args.execute:
                    await session.execute(text("SET TRANSACTION READ ONLY"))
                    await session.execute(text("SET LOCAL statement_timeout = '30s'"))
                    revision = await session.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
                    if revision != "096":
                        raise CleanSlateSafetyError("database_revision_mismatch")
                    plan = await orchestrator.plan(allowlist)
                    await session.rollback()
                    return {"mode": "dry_run", "database_revision": revision, **plan.as_dict()}
                if args.confirm_environment != settings.app_env.value:
                    raise CleanSlateSafetyError("environment_confirmation_mismatch")
                if (
                    settings.app_env.value == "production"
                    and not args.confirm_production_clean_slate
                ):
                    raise CleanSlateSafetyError("production_confirmation_missing")
                if settings.app_env.value == "production" and not args.progress_s3_uri:
                    raise CleanSlateSafetyError("durable_progress_required")
                health = AwsHealthGate(settings, args)
                backup_verified = settings.app_env.value != "production"
                if settings.app_env.value == "production":
                    if allowlist.backup_evidence is None:
                        raise CleanSlateSafetyError("production_backup_evidence_missing")
                    await AwsBackupGate(settings).verify(allowlist.backup_evidence)
                    backup_verified = True
                progress = ProgressStore(
                    artifact_sha256=args.allowlist_sha256,
                    local_path=args.progress_file,
                    s3_uri=args.progress_s3_uri,
                    settings=settings,
                )
                deletion_ids = await orchestrator.execute(
                    allowlist,
                    confirmation=(
                        "EXECUTE PRODUCTION CLEAN SLATE"
                        if settings.app_env.value == "production"
                        else "EXECUTE STAGING CLEAN SLATE"
                    ),
                    backup_verified=backup_verified,
                    health_check=health,
                    progress=progress.record,
                )
                return {
                    "mode": "execute",
                    "deleted_user_count": len(deletion_ids),
                    "deletion_ids": [str(value) for value in deletion_ids],
                }
    finally:
        await engine.dispose()


def emit(value: dict[str, object]) -> None:
    print(json.dumps(value, sort_keys=True), flush=True)


def main() -> None:
    args = parser().parse_args()
    try:
        result = asyncio.run(asyncio.wait_for(run(args), timeout=1800))
        emit(result)
    except CleanSlateSafetyError as error:
        emit({"status": "blocked", "reason": str(error)})
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
