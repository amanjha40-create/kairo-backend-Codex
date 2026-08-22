"""Route-contract tests for Admin System Operations APIs."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.services import get_admin_system_service
from app.auth.deps import CurrentUser, get_current_user
from app.main import app
from app.schemas.admin_communication import (
    AdminCommunicationFullDetailResponse,
    AdminCommunicationResendResponse,
)
from app.schemas.admin_system import (
    AdminSystemActivityItemResponse,
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
from app.schemas.pagination import Page, PageParams
from app.services.admin_system_service import AdminSystemService


def _status() -> AdminSystemStatusResponse:
    return AdminSystemStatusResponse(
        overall_status="degraded",
        checked_at=datetime.now(tz=UTC),
        dependencies=[
            AdminSystemStatusDependencyResponse(
                key="postgresql",
                name="PostgreSQL",
                status="healthy",
                checked_at=datetime.now(tz=UTC),
                latency_ms=12,
                critical=True,
            ),
            AdminSystemStatusDependencyResponse(
                key="redis",
                name="Redis",
                status="degraded",
                checked_at=datetime.now(tz=UTC),
                reason="Connectivity check failed.",
            ),
        ],
    )


def _runtime() -> AdminSystemRuntimeResponse:
    return AdminSystemRuntimeResponse(
        environment="staging",
        application_name="kairo-backend",
        application_version="1.2.3",
        api_version_prefix="/api/v1",
        runtime_started_at=datetime.now(tz=UTC),
        checked_at=datetime.now(tz=UTC),
        python_version="3.12.4",
        job_backend="sqs",
        resume_processing_enabled=True,
        email_backend="brevo",
        email_send_enabled=True,
        phone_otp_backend="staging_fixed",
        release=AdminSystemReleaseResponse(
            git_sha="abc123",
            build_id="build-1",
            deployed_at="2026-08-22T00:00:00Z",
        ),
        migration=AdminSystemMigrationStatusResponse(
            current_revision="069",
            expected_revision="069",
            matches_expected=True,
        ),
    )


def _workloads() -> AdminSystemWorkloadsResponse:
    return AdminSystemWorkloadsResponse(
        generated_at=datetime.now(tz=UTC),
        workloads=[
            AdminSystemWorkloadSummaryResponse(
                key="email_delivery",
                name="Email delivery",
                status="healthy",
                pending=1,
                processing=0,
                succeeded_recent=10,
                failed=0,
                retryable=0,
            )
        ],
    )


def _failures() -> AdminSystemFailuresResponse:
    return AdminSystemFailuresResponse(
        generated_at=datetime.now(tz=UTC),
        items=[
            AdminSystemFailureItemResponse(
                kind="communication",
                public_id=UUID("00000000-0000-0000-0000-000000000101"),
                category="delivery",
                subject_reference="verification_outreach",
                title="Email delivery failed",
                status="failed",
                first_failure_at=datetime.now(tz=UTC),
                latest_failure_at=datetime.now(tz=UTC),
                retry_count=1,
                safe_error="provider_timeout",
                retry_supported=True,
                retry_reference="00000000-0000-0000-0000-000000000101",
            )
        ],
    )


def _incident_detail() -> AdminSystemIncidentDetailResponse:
    return AdminSystemIncidentDetailResponse(
        public_id=UUID("00000000-0000-0000-0000-000000000201"),
        title="Email provider degraded",
        summary="Repeated delivery failures exceeded the threshold.",
        category="delivery",
        severity="high",
        status="open",
        source="manual",
        opened_at=datetime.now(tz=UTC),
        resolved_at=None,
        created_by_user_id=UUID("00000000-0000-0000-0000-000000000999"),
        resolved_by_user_id=None,
        reference_type="communication",
        reference_public_id=UUID("00000000-0000-0000-0000-000000000101"),
        updated_at=datetime.now(tz=UTC),
        history=[
            AdminSystemIncidentEventResponse(
                public_id=UUID("00000000-0000-0000-0000-000000000301"),
                actor_user_id=UUID("00000000-0000-0000-0000-000000000999"),
                event_type="incident_created",
                detail="Opened manually.",
                metadata={},
                created_at=datetime.now(tz=UTC),
            )
        ],
    )


class FakeAdminSystemService:
    async def get_status(self) -> AdminSystemStatusResponse:
        return _status()

    async def get_runtime(self) -> AdminSystemRuntimeResponse:
        return _runtime()

    async def get_workloads(self) -> AdminSystemWorkloadsResponse:
        return _workloads()

    async def get_failures(self) -> AdminSystemFailuresResponse:
        return _failures()

    async def list_activity(self, params):  # noqa: ANN001
        return Page[AdminSystemActivityItemResponse].create(
            items=[
                AdminSystemActivityItemResponse(
                    kind="notification",
                    public_id=UUID("00000000-0000-0000-0000-000000000401"),
                    occurred_at=datetime.now(tz=UTC),
                    title="notification_dispatch_failed",
                    detail="failed",
                    status="failed",
                )
            ],
            total=1,
            params=PageParams(page=params.page, page_size=params.page_size),
        )

    async def list_incidents(
        self,
        params: AdminSystemIncidentListParams,
    ) -> Page[AdminSystemIncidentListItemResponse]:
        detail = _incident_detail()
        item = AdminSystemIncidentListItemResponse(**detail.model_dump(exclude={"history"}))
        return Page[AdminSystemIncidentListItemResponse].create(
            items=[item],
            total=1,
            params=PageParams(page=params.page, page_size=params.page_size),
        )

    async def get_incident(self, incident_public_id: UUID) -> AdminSystemIncidentDetailResponse:  # noqa: ARG002
        return _incident_detail()

    async def create_incident(
        self,
        actor: CurrentUser,  # noqa: ARG002
        payload: AdminSystemCreateIncidentRequest,  # noqa: ARG002
    ) -> AdminSystemIncidentDetailResponse:
        return _incident_detail()

    async def update_incident(
        self,
        actor: CurrentUser,  # noqa: ARG002
        incident_public_id: UUID,  # noqa: ARG002
        payload: AdminSystemUpdateIncidentRequest,  # noqa: ARG002
    ) -> AdminSystemIncidentDetailResponse:
        return _incident_detail().model_copy(update={"status": "monitoring"})

    async def resolve_incident(
        self,
        actor: CurrentUser,  # noqa: ARG002
        incident_public_id: UUID,  # noqa: ARG002
        payload: AdminSystemResolveIncidentRequest,  # noqa: ARG002
    ) -> AdminSystemIncidentDetailResponse:
        return _incident_detail().model_copy(update={"status": "resolved"})

    async def retry_failed_communication(
        self,
        communication_public_id: UUID,  # noqa: ARG002
        *,
        actor_user_id: UUID,  # noqa: ARG002
    ) -> AdminSystemRetryResponse:
        return AdminSystemRetryResponse(
            operation="retry_failed_communication",
            reference_public_id=UUID("00000000-0000-0000-0000-000000000101"),
            subject_public_id=UUID("00000000-0000-0000-0000-000000000501"),
            message="Communication retry requested successfully.",
        )


async def _allow_admin() -> SimpleNamespace:
    return SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000999"),
        email="admin@kairo.test",
        role="admin",
    )


async def _candidate_user() -> CurrentUser:
    return CurrentUser(id=uuid4(), email="candidate@kairo.test", role="user")


@pytest.mark.asyncio
async def test_admin_system_routes_return_backend_truth_for_authorized_operator() -> None:
    app.dependency_overrides[get_admin_system_service] = lambda: FakeAdminSystemService()
    app.dependency_overrides[get_current_user] = _allow_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        status_response = await client.get("/api/v1/admin/system/status")
        runtime_response = await client.get("/api/v1/admin/system/runtime")
        workloads_response = await client.get("/api/v1/admin/system/workloads")
        failures_response = await client.get("/api/v1/admin/system/failures")
        activity_response = await client.get("/api/v1/admin/system/activity?page=1&page_size=10")
        incidents_response = await client.get("/api/v1/admin/system/incidents?page=1&page_size=10")
        detail_response = await client.get(
            "/api/v1/admin/system/incidents/00000000-0000-0000-0000-000000000201"
        )

    app.dependency_overrides.clear()

    assert status_response.status_code == 200
    assert status_response.json()["overall_status"] == "degraded"
    assert runtime_response.status_code == 200
    assert runtime_response.json()["migration"]["matches_expected"] is True
    assert workloads_response.status_code == 200
    assert workloads_response.json()["workloads"][0]["key"] == "email_delivery"
    assert failures_response.status_code == 200
    assert failures_response.json()["items"][0]["retry_supported"] is True
    assert activity_response.status_code == 200
    assert activity_response.json()["items"][0]["kind"] == "notification"
    assert incidents_response.status_code == 200
    assert incidents_response.json()["items"][0]["title"] == "Email provider degraded"
    assert detail_response.status_code == 200
    assert detail_response.json()["history"][0]["event_type"] == "incident_created"


@pytest.mark.asyncio
async def test_admin_system_mutation_routes_return_expected_shapes() -> None:
    app.dependency_overrides[get_admin_system_service] = lambda: FakeAdminSystemService()
    app.dependency_overrides[get_current_user] = _allow_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/admin/system/incidents",
            json={
                "title": "Email provider degraded",
                "summary": "Repeated failures exceeded the threshold.",
                "category": "delivery",
                "severity": "high",
            },
        )
        updated = await client.patch(
            "/api/v1/admin/system/incidents/00000000-0000-0000-0000-000000000201",
            json={"status": "monitoring"},
        )
        resolved = await client.post(
            "/api/v1/admin/system/incidents/00000000-0000-0000-0000-000000000201/resolve",
            json={"reason": "Provider recovered."},
        )
        retried = await client.post(
            "/api/v1/admin/system/retries/communications/00000000-0000-0000-0000-000000000101"
        )

    app.dependency_overrides.clear()

    assert created.status_code == 201
    assert created.json()["title"] == "Email provider degraded"
    assert updated.status_code == 200
    assert updated.json()["status"] == "monitoring"
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    assert retried.status_code == 200
    assert retried.json()["operation"] == "retry_failed_communication"


@pytest.mark.asyncio
async def test_admin_system_routes_require_authentication_and_permission() -> None:
    app.dependency_overrides[get_admin_system_service] = lambda: FakeAdminSystemService()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        unauthenticated = await client.get("/api/v1/admin/system/status")

    app.dependency_overrides[get_current_user] = _candidate_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        forbidden_read = await client.get("/api/v1/admin/system/status")
        forbidden_retry = await client.post(
            "/api/v1/admin/system/retries/communications/00000000-0000-0000-0000-000000000101"
        )

    app.dependency_overrides.clear()

    assert unauthenticated.status_code == 401
    assert forbidden_read.status_code == 403
    assert forbidden_retry.status_code == 403


@pytest.mark.asyncio
async def test_retry_failed_communication_uses_resend_notification_public_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notification_public_id = UUID("00000000-0000-0000-0000-000000000501")

    class FakeAdminCommunicationService:
        def __init__(self, session):  # noqa: ANN001
            self.session = session

        async def resend(
            self,
            communication_public_id: UUID,  # noqa: ARG002
            *,
            actor_user_id: UUID,  # noqa: ARG002
        ) -> AdminCommunicationResendResponse:
            return AdminCommunicationResendResponse(
                communication=AdminCommunicationFullDetailResponse.model_construct(
                    notification_public_id=notification_public_id
                )
            )

    monkeypatch.setattr(
        "app.services.admin_system_service.AdminCommunicationService",
        FakeAdminCommunicationService,
    )

    service = object.__new__(AdminSystemService)
    service._session = object()  # noqa: SLF001
    service._settings = None  # noqa: SLF001

    response = await service.retry_failed_communication(
        UUID("00000000-0000-0000-0000-000000000101"),
        actor_user_id=UUID("00000000-0000-0000-0000-000000000999"),
    )

    assert response.subject_public_id == notification_public_id
