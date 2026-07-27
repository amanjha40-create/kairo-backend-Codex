"""Contract tests for the Admin Trust Registry projections."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_trust_registry_admin_service
from app.main import app
from app.schemas.pagination import Page
from app.schemas.trust_registry import (
    TrustRegistryAdminDetailResponse,
    TrustRegistryAdminMetricsResponse,
    TrustRegistryAdminRecordResponse,
)


def _record() -> TrustRegistryAdminRecordResponse:
    return TrustRegistryAdminRecordResponse(
        public_id=uuid4(),
        registry_code="KR-ORG-TEST1234",
        legal_name="Kairo Test University",
        display_name="Kairo University",
        organization_type="educational_institution",
        country="IN",
        state_province=None,
        website="https://example.test",
        lifecycle_status="active",
        trust_status="trusted",
        registry_confidence_score=95,
        trust_metadata={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        aliases=["Kairo Institute"],
        state="verified",
        active_case_count=1,
        total_verifications=2,
    )


class FakeTrustRegistryAdminService:
    async def list_records(self, params):  # noqa: ANN001
        item = _record()
        return Page.create(items=[item], total=1, params=params)

    async def get_detail(self, registry_public_id):  # noqa: ANN001
        item = _record()
        return TrustRegistryAdminDetailResponse(**item.model_dump(), contacts=[], activity=[])

    async def metrics(self):
        return TrustRegistryAdminMetricsResponse(
            total=1,
            verified=1,
            unverified=0,
            duplicates=0,
            contacts_approved=0,
            contacts_bounced=0,
        )


async def _override_admin_user() -> CurrentUser:
    return CurrentUser(
        id=UUID("00000000-0000-0000-0000-000000000999"),
        email="admin@kairo.test",
        role="admin",
    )


@pytest.mark.asyncio
async def test_admin_registry_projection_routes_use_canonical_namespace() -> None:
    app.dependency_overrides[get_current_user] = _override_admin_user
    app.dependency_overrides[get_trust_registry_admin_service] = (
        lambda: FakeTrustRegistryAdminService()
    )
    registry_id = uuid4()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        list_response = await client.get("/api/v1/admin/trust-registry?paginate=true")
        metrics_response = await client.get("/api/v1/admin/trust-registry/metrics")
        search_response = await client.get("/api/v1/admin/trust-registry/search?search=Kairo")
        detail_response = await client.get(f"/api/v1/admin/trust-registry/{registry_id}")
        legacy_response = await client.get("/api/admin/registry")
    app.dependency_overrides.clear()

    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["aliases"] == ["Kairo Institute"]
    assert metrics_response.status_code == 200
    assert metrics_response.json()["verified"] == 1
    assert search_response.status_code == 200
    assert detail_response.status_code == 200
    assert legacy_response.status_code == 404
