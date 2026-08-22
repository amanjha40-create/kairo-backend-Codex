"""Canonical Admin System Operations service."""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from alembic.config import Config
from alembic.script import ScriptDirectory
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies.verification_admin import CurrentUser
from app.config import Settings
from app.db.health import ping_database
from app.exceptions import ConflictError, NotFoundError
from app.infrastructure.redis import ping_redis
from app.infrastructure.s3.client import get_s3_client
from app.models.email_delivery_log import EmailDeliveryLog
from app.models.notification import Notification
from app.models.notification_delivery import NotificationDelivery
from app.models.notification_event import NotificationEvent
from app.models.resume_processing_job import ResumeProcessingJob
from app.models.system_incident import SystemIncident
from app.models.system_incident_event import SystemIncidentEvent
from app.models.verification_connector_run import VerificationConnectorRun
from app.runtime_metadata import APP_STARTED_AT
from app.schemas.admin_system import (
    AdminSystemActivityItemResponse,
    AdminSystemActivityParams,
    AdminSystemCreateIncidentRequest,
    AdminSystemFailureItemResponse,
    AdminSystemFailuresResponse,
    AdminSystemIncidentDetailResponse,
    AdminSystemIncidentEventResponse,
    AdminSystemIncidentListItemResponse,
    AdminSystemIncidentListParams,
    AdminSystemMigrationStatusResponse,
    AdminSystemReleaseResponse,
    AdminSystemResolveIncidentRequest,
    AdminSystemRetryResponse,
    AdminSystemRuntimeResponse,
    AdminSystemStatusDependencyResponse,
    AdminSystemStatusResponse,
    AdminSystemUpdateIncidentRequest,
    AdminSystemWorkloadsResponse,
    AdminSystemWorkloadSummaryResponse,
)
from app.schemas.pagination import Page
from app.services.admin_communication_service import AdminCommunicationService

_WORKLOAD_WINDOW = timedelta(hours=24)
_FAILURE_LIMIT = 25


@dataclass(slots=True)
class _DependencyCheck:
    key: str
    name: str
    critical: bool
    status: str
    checked_at: datetime
    latency_ms: int | None = None
    reason: str | None = None


class AdminSystemService:
    """Project truthful operational state for the Admin System Operations surface."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    async def get_status(self) -> AdminSystemStatusResponse:
        checks = [
            await self._check_api_process(),
            await self._check_database(),
            await self._check_redis(),
            await self._check_object_storage(),
        ]
        overall = self._derive_overall_status(checks)
        checked_at = max(check.checked_at for check in checks)
        return AdminSystemStatusResponse(
            overall_status=overall,
            checked_at=checked_at,
            dependencies=[
                AdminSystemStatusDependencyResponse(
                    key=check.key,
                    name=check.name,
                    status=check.status,  # type: ignore[arg-type]
                    checked_at=check.checked_at,
                    critical=check.critical,
                    latency_ms=check.latency_ms,
                    reason=check.reason,
                )
                for check in checks
            ],
        )

    async def get_runtime(self) -> AdminSystemRuntimeResponse:
        return AdminSystemRuntimeResponse(
            environment=self._settings.app_env.value,
            application_name=self._settings.app_name,
            application_version=self._settings.app_version,
            api_version_prefix=self._settings.api_v1_prefix,
            runtime_started_at=APP_STARTED_AT,
            checked_at=datetime.now(tz=UTC),
            python_version=sys.version.split(" ", maxsplit=1)[0],
            job_backend=self._settings.job_backend,
            resume_processing_enabled=self._settings.resume_processing_enabled,
            email_backend=self._settings.email_backend,
            email_send_enabled=self._settings.email_send_enabled,
            phone_otp_backend=self._settings.phone_otp_backend,
            release=AdminSystemReleaseResponse(
                git_sha=self._settings.app_git_sha,
                build_id=self._settings.app_build_id,
                deployed_at=self._settings.app_deployed_at,
            ),
            migration=await self._migration_status(),
        )

    async def get_workloads(self) -> AdminSystemWorkloadsResponse:
        now = datetime.now(tz=UTC)
        window_start = now - _WORKLOAD_WINDOW
        workloads = [
            await self._email_delivery_workload(window_start),
            await self._notification_workload(window_start),
            await self._resume_processing_workload(window_start),
            await self._connector_workload(window_start),
        ]
        return AdminSystemWorkloadsResponse(generated_at=now, workloads=workloads)

    async def get_failures(self) -> AdminSystemFailuresResponse:
        now = datetime.now(tz=UTC)
        items = [
            *(await self._communication_failures()),
            *(await self._resume_failures()),
            *(await self._connector_failures()),
        ]
        items.sort(key=lambda item: item.latest_failure_at, reverse=True)
        return AdminSystemFailuresResponse(generated_at=now, items=items[:_FAILURE_LIMIT])

    async def list_activity(
        self,
        params: AdminSystemActivityParams,
    ) -> Page[AdminSystemActivityItemResponse]:
        items = [
            *(await self._incident_activity()),
            *(await self._notification_activity()),
            *(await self._resume_activity()),
            *(await self._connector_activity()),
        ]
        items.sort(key=lambda item: item.occurred_at, reverse=True)
        return Page[AdminSystemActivityItemResponse].create(
            items=items[params.slice_start:params.slice_end],
            total=len(items),
            params=params,
        )

    async def list_incidents(
        self,
        params: AdminSystemIncidentListParams,
    ) -> Page[AdminSystemIncidentListItemResponse]:
        stmt: Select[tuple[SystemIncident]] = select(SystemIncident)
        stmt = self._apply_incident_filters(stmt, params)
        total = int(
            (await self._session.scalar(select(func.count()).select_from(stmt.subquery()))) or 0
        )
        rows = await self._session.execute(
            stmt.order_by(SystemIncident.opened_at.desc(), SystemIncident.id.desc())
            .offset(params.slice_start)
            .limit(params.limit or 20)
        )
        incidents = list(rows.scalars().unique().all())
        return Page[AdminSystemIncidentListItemResponse].create(
            items=[self._to_incident_list_item(item) for item in incidents],
            total=total,
            params=params,
        )

    async def get_incident(self, incident_public_id: UUID) -> AdminSystemIncidentDetailResponse:
        incident = await self._require_incident(incident_public_id)
        return self._to_incident_detail(incident)

    async def create_incident(
        self,
        actor: CurrentUser,
        payload: AdminSystemCreateIncidentRequest,
    ) -> AdminSystemIncidentDetailResponse:
        incident = SystemIncident(
            title=payload.title,
            summary=payload.summary,
            category=payload.category.lower(),
            severity=payload.severity,
            status="open",
            source="manual",
            reference_type=payload.reference_type.lower() if payload.reference_type else None,
            reference_public_id=payload.reference_public_id,
            created_by_user_id=actor.id,
        )
        self._session.add(incident)
        await self._session.flush()
        await self._append_incident_event(
            incident,
            actor_user_id=actor.id,
            event_type="incident_created",
            detail=f"Incident opened as {payload.severity}.",
            metadata={"severity": payload.severity, "category": payload.category.lower()},
        )
        await self._session.commit()
        return await self.get_incident(incident.public_id)

    async def update_incident(
        self,
        actor: CurrentUser,
        incident_public_id: UUID,
        payload: AdminSystemUpdateIncidentRequest,
    ) -> AdminSystemIncidentDetailResponse:
        incident = await self._require_incident(incident_public_id)
        if incident.status == "resolved":
            raise ConflictError("Resolved incidents cannot be modified.")
        changes: list[str] = []
        if payload.title is not None and payload.title != incident.title:
            incident.title = payload.title
            changes.append("title")
        if payload.summary is not None and payload.summary != incident.summary:
            incident.summary = payload.summary
            changes.append("summary")
        if payload.category is not None and payload.category.lower() != incident.category:
            incident.category = payload.category.lower()
            changes.append("category")
        if payload.severity is not None and payload.severity != incident.severity:
            incident.severity = payload.severity
            changes.append("severity")
        if payload.status is not None and payload.status != incident.status:
            incident.status = payload.status
            changes.append("status")
        if not changes:
            return self._to_incident_detail(incident)
        await self._append_incident_event(
            incident,
            actor_user_id=actor.id,
            event_type="incident_updated",
            detail=f"Updated {', '.join(changes)}.",
            metadata={"fields": changes},
        )
        await self._session.commit()
        return await self.get_incident(incident.public_id)

    async def resolve_incident(
        self,
        actor: CurrentUser,
        incident_public_id: UUID,
        payload: AdminSystemResolveIncidentRequest,
    ) -> AdminSystemIncidentDetailResponse:
        incident = await self._require_incident(incident_public_id)
        if incident.status == "resolved":
            raise ConflictError("Incident is already resolved.")
        incident.status = "resolved"
        incident.resolved_at = datetime.now(tz=UTC)
        incident.resolved_by_user_id = actor.id
        await self._append_incident_event(
            incident,
            actor_user_id=actor.id,
            event_type="incident_resolved",
            detail=payload.reason,
            metadata={"reason": payload.reason},
        )
        await self._session.commit()
        return await self.get_incident(incident.public_id)

    async def retry_failed_communication(
        self,
        communication_public_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> AdminSystemRetryResponse:
        communication = await AdminCommunicationService(self._session).resend(
            communication_public_id,
            actor_user_id=actor_user_id,
        )
        return AdminSystemRetryResponse(
            operation="retry_failed_communication",
            reference_public_id=communication_public_id,
            subject_public_id=communication.communication.notification_public_id,
            message="Communication retry requested successfully.",
        )

    async def _check_api_process(self) -> _DependencyCheck:
        now = datetime.now(tz=UTC)
        return _DependencyCheck(
            key="api_process",
            name="API process",
            critical=True,
            status="healthy",
            checked_at=now,
            latency_ms=0,
        )

    async def _check_database(self) -> _DependencyCheck:
        started = time.perf_counter()
        now = datetime.now(tz=UTC)
        try:
            await ping_database(self._session)
            latency_ms = round((time.perf_counter() - started) * 1000)
            return _DependencyCheck(
                key="postgresql",
                name="PostgreSQL",
                critical=True,
                status="healthy",
                checked_at=now,
                latency_ms=latency_ms,
            )
        except Exception:
            return _DependencyCheck(
                key="postgresql",
                name="PostgreSQL",
                critical=True,
                status="unavailable",
                checked_at=now,
                reason="Connectivity check failed.",
            )

    async def _check_redis(self) -> _DependencyCheck:
        started = time.perf_counter()
        now = datetime.now(tz=UTC)
        ok = await ping_redis()
        if ok:
            return _DependencyCheck(
                key="redis",
                name="Redis",
                critical=False,
                status="healthy",
                checked_at=now,
                latency_ms=round((time.perf_counter() - started) * 1000),
            )
        return _DependencyCheck(
            key="redis",
            name="Redis",
            critical=False,
            status="degraded",
            checked_at=now,
            reason="Connectivity check failed.",
        )

    async def _check_object_storage(self) -> _DependencyCheck:
        now = datetime.now(tz=UTC)
        if not self._settings.resume_processing_enabled or not self._settings.s3_documents_bucket:
            return _DependencyCheck(
                key="object_storage",
                name="Object storage",
                critical=False,
                status="unknown",
                checked_at=now,
                reason="No canonical storage check is enabled for this deployment.",
            )

        started = time.perf_counter()

        def head_bucket() -> None:
            client = get_s3_client(self._settings)
            client.head_bucket(Bucket=self._settings.s3_documents_bucket)

        try:
            await asyncio.to_thread(head_bucket)
            return _DependencyCheck(
                key="object_storage",
                name="Object storage",
                critical=False,
                status="healthy",
                checked_at=now,
                latency_ms=round((time.perf_counter() - started) * 1000),
            )
        except (BotoCoreError, ClientError):
            return _DependencyCheck(
                key="object_storage",
                name="Object storage",
                critical=False,
                status="degraded",
                checked_at=now,
                reason="Bucket check failed.",
            )

    def _derive_overall_status(self, checks: Sequence[_DependencyCheck]) -> str:
        if any(check.critical and check.status == "unavailable" for check in checks):
            return "unavailable"
        if any(check.status in {"degraded", "unavailable"} for check in checks):
            return "degraded"
        if any(check.status == "healthy" for check in checks):
            return "healthy"
        return "unknown"

    async def _migration_status(self) -> AdminSystemMigrationStatusResponse:
        root = Path(__file__).resolve().parents[2]
        config = Config()
        config.set_main_option("script_location", str(root / "alembic"))
        script = ScriptDirectory.from_config(config)
        expected_heads = script.get_heads()
        current_rows = list(
            (
                await self._session.execute(text("SELECT version_num FROM alembic_version"))
            ).scalars()
        )
        current = current_rows[0] if current_rows else None
        expected = expected_heads[0] if len(expected_heads) == 1 else None
        return AdminSystemMigrationStatusResponse(
            current_revision=current,
            expected_revision=expected,
            matches_expected=(len(expected_heads) == 1 and current == expected),
            multiple_heads=len(expected_heads) > 1,
        )

    async def _email_delivery_workload(
        self,
        window_start: datetime,
    ) -> AdminSystemWorkloadSummaryResponse:
        pending_statuses = {"queued"}
        processing = 0
        pending = await self._count_model(
            EmailDeliveryLog,
            EmailDeliveryLog.status.in_(pending_statuses),
        )
        failed = await self._count_model(
            EmailDeliveryLog,
            EmailDeliveryLog.status == "failed",
            EmailDeliveryLog.failed_at >= window_start,
        )
        succeeded_recent = await self._count_model(
            EmailDeliveryLog,
            EmailDeliveryLog.status == "sent",
            EmailDeliveryLog.sent_at >= window_start,
        )
        retryable = await self._count_retryable_failed_communications()
        oldest_pending_at = await self._scalar_datetime(
            select(func.min(EmailDeliveryLog.queued_at)).where(EmailDeliveryLog.status.in_(pending_statuses))
        )
        latest_success_at = await self._scalar_datetime(
            select(func.max(EmailDeliveryLog.sent_at)).where(EmailDeliveryLog.status == "sent")
        )
        latest_failure_at = await self._scalar_datetime(
            select(func.max(EmailDeliveryLog.failed_at)).where(EmailDeliveryLog.status == "failed")
        )
        return AdminSystemWorkloadSummaryResponse(
            key="email_delivery",
            name="Email delivery",
            status=self._derive_workload_status(failed=failed, pending=pending),
            pending=pending,
            processing=processing,
            succeeded_recent=succeeded_recent,
            failed=failed,
            retryable=retryable,
            oldest_pending_at=oldest_pending_at,
            latest_success_at=latest_success_at,
            latest_failure_at=latest_failure_at,
            note=(
                "Transactional delivery attempts persisted through communications and "
                "notification logs."
            ),
        )

    async def _notification_workload(
        self,
        window_start: datetime,
    ) -> AdminSystemWorkloadSummaryResponse:
        pending = await self._count_model(
            NotificationDelivery,
            NotificationDelivery.status.in_(("pending", "queued")),
        )
        processing = await self._count_model(
            NotificationDelivery,
            NotificationDelivery.status == "processing",
        )
        failed = await self._count_model(
            NotificationDelivery,
            NotificationDelivery.status == "failed",
            NotificationDelivery.failed_at >= window_start,
        )
        succeeded_recent = await self._count_model(
            NotificationDelivery,
            NotificationDelivery.status.in_(("sent", "delivered")),
            NotificationDelivery.created_at >= window_start,
        )
        oldest_pending_at = await self._scalar_datetime(
            select(func.min(NotificationDelivery.created_at)).where(
                NotificationDelivery.status.in_(("pending", "queued"))
            )
        )
        latest_success_at = await self._scalar_datetime(
            select(func.max(NotificationDelivery.delivered_at)).where(
                NotificationDelivery.status.in_(("sent", "delivered"))
            )
        )
        latest_failure_at = await self._scalar_datetime(
            select(func.max(NotificationDelivery.failed_at)).where(
                NotificationDelivery.status == "failed"
            )
        )
        return AdminSystemWorkloadSummaryResponse(
            key="notifications",
            name="Notification dispatch",
            status=self._derive_workload_status(failed=failed, pending=pending + processing),
            pending=pending,
            processing=processing,
            succeeded_recent=succeeded_recent,
            failed=failed,
            retryable=0,
            oldest_pending_at=oldest_pending_at,
            latest_success_at=latest_success_at,
            latest_failure_at=latest_failure_at,
            note="Includes in-app and email dispatch attempts.",
        )

    async def _resume_processing_workload(
        self,
        window_start: datetime,
    ) -> AdminSystemWorkloadSummaryResponse:
        pending = await self._count_model(
            ResumeProcessingJob,
            ResumeProcessingJob.status == "queued",
        )
        processing = await self._count_model(
            ResumeProcessingJob,
            ResumeProcessingJob.status.in_(("extracting", "parsing")),
        )
        failed = await self._count_model(
            ResumeProcessingJob,
            ResumeProcessingJob.status == "failed",
            ResumeProcessingJob.updated_at >= window_start,
        )
        succeeded_recent = await self._count_model(
            ResumeProcessingJob,
            ResumeProcessingJob.status == "needs_review",
            ResumeProcessingJob.completed_at >= window_start,
        )
        retryable = await self._count_model(
            ResumeProcessingJob,
            ResumeProcessingJob.status == "failed",
            ResumeProcessingJob.attempt_count <= self._settings.resume_max_retries,
        )
        oldest_pending_at = await self._scalar_datetime(
            select(func.min(ResumeProcessingJob.created_at)).where(
                ResumeProcessingJob.status.in_(("queued", "extracting", "parsing"))
            )
        )
        latest_success_at = await self._scalar_datetime(
            select(func.max(ResumeProcessingJob.completed_at)).where(
                ResumeProcessingJob.status == "needs_review"
            )
        )
        latest_failure_at = await self._scalar_datetime(
            select(func.max(ResumeProcessingJob.updated_at)).where(
                ResumeProcessingJob.status == "failed"
            )
        )
        return AdminSystemWorkloadSummaryResponse(
            key="resume_processing",
            name="Resume processing",
            status=self._derive_workload_status(failed=failed, pending=pending + processing),
            pending=pending,
            processing=processing,
            succeeded_recent=succeeded_recent,
            failed=failed,
            retryable=retryable,
            oldest_pending_at=oldest_pending_at,
            latest_success_at=latest_success_at,
            latest_failure_at=latest_failure_at,
            note="Tracks queued, active, and failed resume extraction/parsing jobs.",
        )

    async def _connector_workload(
        self,
        window_start: datetime,
    ) -> AdminSystemWorkloadSummaryResponse:
        pending = await self._count_model(
            VerificationConnectorRun,
            VerificationConnectorRun.status == "queued",
        )
        processing = await self._count_model(
            VerificationConnectorRun,
            VerificationConnectorRun.status.in_(("running", "processing")),
        )
        failed = await self._count_model(
            VerificationConnectorRun,
            VerificationConnectorRun.status == "failed",
            VerificationConnectorRun.started_at >= window_start,
        )
        succeeded_recent = await self._count_model(
            VerificationConnectorRun,
            VerificationConnectorRun.status == "succeeded",
            VerificationConnectorRun.completed_at >= window_start,
        )
        oldest_pending_at = await self._scalar_datetime(
            select(func.min(VerificationConnectorRun.started_at)).where(
                VerificationConnectorRun.status.in_(("queued", "running", "processing"))
            )
        )
        latest_success_at = await self._scalar_datetime(
            select(func.max(VerificationConnectorRun.completed_at)).where(
                VerificationConnectorRun.status == "succeeded"
            )
        )
        latest_failure_at = await self._scalar_datetime(
            select(func.max(VerificationConnectorRun.completed_at)).where(
                VerificationConnectorRun.status == "failed"
            )
        )
        return AdminSystemWorkloadSummaryResponse(
            key="verification_connectors",
            name="Verification connectors",
            status=self._derive_workload_status(failed=failed, pending=pending + processing),
            pending=pending,
            processing=processing,
            succeeded_recent=succeeded_recent,
            failed=failed,
            retryable=0,
            oldest_pending_at=oldest_pending_at,
            latest_success_at=latest_success_at,
            latest_failure_at=latest_failure_at,
            note="Automated connector executions persisted per verification attempt.",
        )

    def _derive_workload_status(self, *, failed: int, pending: int) -> str:
        if failed > 0:
            return "degraded"
        if pending > 100:
            return "degraded"
        return "healthy"

    async def _communication_failures(self) -> list[AdminSystemFailureItemResponse]:
        rows = (
            await self._session.execute(
                select(EmailDeliveryLog)
                .where(EmailDeliveryLog.status == "failed")
                .order_by(EmailDeliveryLog.failed_at.desc(), EmailDeliveryLog.id.desc())
                .limit(10)
            )
        ).scalars().all()
        linked = await AdminCommunicationService(self._session)._load_notification_links(list(rows))  # noqa: SLF001
        retryable_ids = {
            item.id
            for item in rows
            if (delivery := linked.get(item.id)) is not None and delivery.notification is not None
        }
        return [
            AdminSystemFailureItemResponse(
                kind="communication",
                public_id=row.public_id,
                category="delivery",
                subject_reference=row.template_key,
                title=f"Email delivery failed for {row.template_key}",
                status=row.status,
                first_failure_at=row.failed_at or row.created_at,
                latest_failure_at=row.failed_at or row.updated_at,
                retry_count=max(row.attempt_count, 0),
                safe_error=row.error_code or row.error_message,
                retry_supported=row.id in retryable_ids,
                retry_reference=str(row.public_id) if row.id in retryable_ids else None,
            )
            for row in rows
        ]

    async def _resume_failures(self) -> list[AdminSystemFailureItemResponse]:
        rows = (
            await self._session.execute(
                select(ResumeProcessingJob)
                .where(ResumeProcessingJob.status == "failed")
                .order_by(ResumeProcessingJob.updated_at.desc(), ResumeProcessingJob.id.desc())
                .limit(10)
            )
        ).scalars().all()
        return [
            AdminSystemFailureItemResponse(
                kind="resume_processing",
                public_id=row.id,
                category="processing",
                subject_reference=str(row.resume_document_id),
                title="Resume processing failed",
                status=row.status,
                first_failure_at=row.updated_at,
                latest_failure_at=row.updated_at,
                retry_count=max(row.attempt_count - 1, 0),
                safe_error=row.sanitized_failure_code or row.failure_category,
                retry_supported=False,
            )
            for row in rows
            if row.updated_at is not None
        ]

    async def _connector_failures(self) -> list[AdminSystemFailureItemResponse]:
        rows = (
            await self._session.execute(
                select(VerificationConnectorRun)
                .where(VerificationConnectorRun.status == "failed")
                .order_by(
                    VerificationConnectorRun.completed_at.desc(),
                    VerificationConnectorRun.id.desc(),
                )
                .limit(10)
            )
        ).scalars().all()
        return [
            AdminSystemFailureItemResponse(
                kind="verification_connector",
                public_id=row.public_id,
                category="verification_connector",
                subject_reference=row.connector_key,
                title=f"Connector run failed for {row.connector_key}",
                status=row.status,
                first_failure_at=row.completed_at or row.started_at,
                latest_failure_at=row.completed_at or row.started_at,
                retry_count=max(row.retry_count, 0),
                safe_error=str(
                    (row.error or {}).get("code")
                    or (row.error or {}).get("type")
                    or "connector_failed"
                ),
                retry_supported=False,
            )
            for row in rows
        ]

    async def _incident_activity(self) -> list[AdminSystemActivityItemResponse]:
        rows = (
            await self._session.execute(
                select(SystemIncidentEvent).options(selectinload(SystemIncidentEvent.incident))
                .order_by(SystemIncidentEvent.created_at.desc())
                .limit(15)
            )
        ).scalars().all()
        return [
            AdminSystemActivityItemResponse(
                kind="incident",
                public_id=row.public_id,
                occurred_at=row.created_at,
                title=row.event_type.replace("_", " "),
                detail=row.detail,
                actor_user_id=row.actor_user_id,
                subject_type="system_incident",
                subject_public_id=incident_public_id,
            )
            for row in rows
            for incident_public_id in [self._incident_public_id_from_event(row)]
            if incident_public_id is not None
        ]

    async def _notification_activity(self) -> list[AdminSystemActivityItemResponse]:
        rows = (
            await self._session.execute(
                select(NotificationEvent)
                .options(selectinload(NotificationEvent.notification))
                .where(NotificationEvent.event_type.in_((
                    "notification_dispatch_completed",
                    "notification_dispatch_failed",
                    "notification_resend_requested",
                )))
                .order_by(NotificationEvent.created_at.desc())
                .limit(10)
            )
        ).scalars().all()
        return [
            AdminSystemActivityItemResponse(
                kind="notification",
                public_id=row.public_id,
                occurred_at=row.created_at,
                title=row.event_type.replace("_", " "),
                detail=row.status,
                status=row.status,
                actor_user_id=row.actor_user_id,
                subject_type="notification",
                subject_public_id=(
                    row.notification.public_id if row.notification is not None else None
                ),
            )
            for row in rows
        ]

    async def _resume_activity(self) -> list[AdminSystemActivityItemResponse]:
        rows = (
            await self._session.execute(
                select(ResumeProcessingJob)
                .where(ResumeProcessingJob.status.in_(("failed", "needs_review")))
                .order_by(ResumeProcessingJob.updated_at.desc())
                .limit(10)
            )
        ).scalars().all()
        return [
            AdminSystemActivityItemResponse(
                kind="resume_processing",
                public_id=row.id,
                occurred_at=row.completed_at or row.updated_at,
                title=f"Resume job {row.status.replace('_', ' ')}",
                detail=(
                    row.sanitized_failure_code
                    if row.status == "failed"
                    else "Parsed result ready for review."
                ),
                status=row.status,
                subject_type="resume_document",
                subject_public_id=None,
            )
            for row in rows
            if (row.completed_at or row.updated_at) is not None
        ]

    async def _connector_activity(self) -> list[AdminSystemActivityItemResponse]:
        rows = (
            await self._session.execute(
                select(VerificationConnectorRun)
                .where(VerificationConnectorRun.status.in_(("failed", "succeeded")))
                .order_by(VerificationConnectorRun.started_at.desc())
                .limit(10)
            )
        ).scalars().all()
        return [
            AdminSystemActivityItemResponse(
                kind="verification_connector",
                public_id=row.public_id,
                occurred_at=row.completed_at or row.started_at,
                title=f"Connector {row.connector_key} {row.status}",
                detail=None,
                status=row.status,
                subject_type="verification_request",
                subject_public_id=None,
            )
            for row in rows
        ]

    def _apply_incident_filters(
        self,
        stmt: Select[tuple[SystemIncident]],
        params: AdminSystemIncidentListParams,
    ) -> Select[tuple[SystemIncident]]:
        if params.status != "all":
            stmt = stmt.where(SystemIncident.status == params.status)
        if params.severity != "all":
            stmt = stmt.where(SystemIncident.severity == params.severity)
        if params.category != "all":
            stmt = stmt.where(SystemIncident.category == params.category.lower())
        return stmt

    async def _require_incident(self, incident_public_id: UUID) -> SystemIncident:
        incident = (
            await self._session.execute(
                select(SystemIncident)
                .where(SystemIncident.public_id == incident_public_id)
                .options(selectinload(SystemIncident.events))
            )
        ).scalar_one_or_none()
        if incident is None:
            raise NotFoundError("System incident not found")
        return incident

    async def _append_incident_event(
        self,
        incident: SystemIncident,
        *,
        actor_user_id: UUID | None,
        event_type: str,
        detail: str | None,
        metadata: dict[str, object],
    ) -> None:
        self._session.add(
            SystemIncidentEvent(
                incident_id=incident.id,
                actor_user_id=actor_user_id,
                event_type=event_type,
                detail=detail,
                metadata_payload=metadata,
            )
        )
        await self._session.flush()

    def _to_incident_list_item(
        self,
        incident: SystemIncident,
    ) -> AdminSystemIncidentListItemResponse:
        return AdminSystemIncidentListItemResponse(
            public_id=incident.public_id,
            title=incident.title,
            summary=incident.summary,
            category=incident.category,
            severity=incident.severity,  # type: ignore[arg-type]
            status=incident.status,  # type: ignore[arg-type]
            source=incident.source,
            opened_at=incident.opened_at,
            resolved_at=incident.resolved_at,
            created_by_user_id=incident.created_by_user_id,
            resolved_by_user_id=incident.resolved_by_user_id,
            reference_type=incident.reference_type,
            reference_public_id=incident.reference_public_id,
            updated_at=incident.updated_at,
        )

    def _to_incident_detail(self, incident: SystemIncident) -> AdminSystemIncidentDetailResponse:
        base = self._to_incident_list_item(incident)
        return AdminSystemIncidentDetailResponse(
            **base.model_dump(),
            history=[
                AdminSystemIncidentEventResponse(
                    public_id=event.public_id,
                    actor_user_id=event.actor_user_id,
                    event_type=event.event_type,
                    detail=event.detail,
                    metadata=event.metadata_payload or {},
                    created_at=event.created_at,
                )
                for event in incident.events
            ],
        )

    async def _count_model(self, model, *criteria) -> int:  # noqa: ANN001
        stmt = select(func.count()).select_from(model)
        if criteria:
            stmt = stmt.where(*criteria)
        return int((await self._session.scalar(stmt)) or 0)

    async def _scalar_datetime(self, stmt) -> datetime | None:  # noqa: ANN001
        return await self._session.scalar(stmt)

    async def _count_retryable_failed_communications(self) -> int:
        stmt = (
            select(func.count())
            .select_from(EmailDeliveryLog)
            .join(
                NotificationDelivery,
                NotificationDelivery.email_delivery_log_id == EmailDeliveryLog.id,
            )
            .join(Notification, Notification.id == NotificationDelivery.notification_id)
            .where(
                EmailDeliveryLog.status == "failed",
                Notification.channel == "email",
            )
        )
        return int((await self._session.scalar(stmt)) or 0)

    def _incident_public_id_from_event(self, event: SystemIncidentEvent) -> UUID | None:
        incident = event.incident
        return incident.public_id if incident is not None else None
