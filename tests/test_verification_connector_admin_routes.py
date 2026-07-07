"""Route-contract tests for verification connector admin APIs."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_connector_registry_service
from app.main import app
from app.schemas.pagination import Page
from app.schemas.verification_connector import (
    VerificationConnectorHealthResponse,
    VerificationConnectorResponse,
    VerificationConnectorRunResponse,
)


class FakeConnectorRegistryService:
    def __init__(self) -> None:
        self._connector_public_id = uuid4()
        self._request_public_id = uuid4()
        self._run_public_id = uuid4()
        self._now = datetime.now(tz=UTC)

    def _connector(self) -> VerificationConnectorResponse:
        return VerificationConnectorResponse(
            public_id=self._connector_public_id,
            connector_key="mock_connector",
            display_name="Mock Verification Connector",
            connector_type="custom",
            supported_capabilities=["employment", "education"],
            supported_registry_types=["*"],
            version="v1",
            health_status="healthy",
            enabled=True,
            priority=100,
            last_health_checked_at=self._now,
            created_at=self._now,
            updated_at=self._now,
        )

    async def list_connectors(self, params):  # noqa: ANN001
        return Page[VerificationConnectorResponse](
            items=[self._connector()],
            total=1,
            page=1,
            page_size=10,
            total_pages=1,
            offset=0,
            limit=10,
        )

    async def get_detail(self, connector_public_id: UUID):  # noqa: ANN001
        return self._connector()

    async def update_connector(self, connector_public_id: UUID, payload):  # noqa: ANN001
        connector = self._connector()
        data = connector.model_dump()
        if payload.enabled is not None:
            data["enabled"] = payload.enabled
        if payload.priority is not None:
            data["priority"] = payload.priority
        if payload.health_status is not None:
            data["health_status"] = payload.health_status
        return VerificationConnectorResponse(**data)

    async def get_health(self, connector_public_id: UUID):  # noqa: ANN001
        return VerificationConnectorHealthResponse(
            connector_public_id=self._connector_public_id,
            connector_key="mock_connector",
            display_name="Mock Verification Connector",
            health_status="healthy",
            enabled=True,
            checked_at=self._now,
        )

    async def list_run_history(self, connector_public_id: UUID, params):  # noqa: ANN001
        return Page[VerificationConnectorRunResponse](
            items=[
                VerificationConnectorRunResponse(
                    public_id=self._run_public_id,
                    connector_public_id=self._connector_public_id,
                    connector_key="mock_connector",
                    verification_request_public_id=self._request_public_id,
                    registry_record_public_id=None,
                    status="succeeded",
                    started_at=self._now,
                    completed_at=self._now,
                    execution_time_ms=125,
                    normalized_result={"status": "verified"},
                    raw_metadata={"connector": "mock_connector"},
                    evidence_references=[],
                    error={},
                    retry_count=0,
                    created_at=self._now,
                    updated_at=self._now,
                )
            ],
            total=1,
            page=1,
            page_size=10,
            total_pages=1,
            offset=0,
            limit=10,
        )


async def _override_current_user() -> CurrentUser:
    return CurrentUser(
        id=UUID("00000000-0000-0000-0000-000000000999"),
        email="reviewer@kairo.test",
        role="hr",
    )


@pytest.mark.asyncio
async def test_connector_admin_routes_return_expected_contracts() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_connector_registry_service] = lambda: FakeConnectorRegistryService()

    transport = ASGITransport(app=app)
    connector_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        list_response = await client.get("/api/v1/admin/verification-connectors?paginate=true&page=1&page_size=10")
        detail_response = await client.get(f"/api/v1/admin/verification-connectors/{connector_public_id}")
        update_response = await client.patch(
            f"/api/v1/admin/verification-connectors/{connector_public_id}",
            json={"enabled": False, "priority": 50, "health_status": "degraded"},
        )
        health_response = await client.get(f"/api/v1/admin/verification-connectors/{connector_public_id}/health")
        runs_response = await client.get(
            f"/api/v1/admin/verification-connectors/{connector_public_id}/runs?paginate=true&page=1&page_size=10"
        )

    app.dependency_overrides.clear()
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert detail_response.status_code == 200
    assert detail_response.json()["connector_key"] == "mock_connector"
    assert update_response.status_code == 200
    assert update_response.json()["enabled"] is False
    assert update_response.json()["health_status"] == "degraded"
    assert health_response.status_code == 200
    assert health_response.json()["health_status"] == "healthy"
    assert runs_response.status_code == 200
    assert runs_response.json()["items"][0]["status"] == "succeeded"
