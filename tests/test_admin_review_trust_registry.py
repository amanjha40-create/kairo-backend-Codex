"""Route-contract tests for Trust Registry actions on admin review endpoints."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_trust_registry_resolution_service
from app.main import app
from app.schemas.trust_registry import TrustRegistryVerificationRequestResolutionResponse
from app.trust_registry.enums import TrustRegistryResolutionState


class FakeTrustRegistryResolutionService:
    async def resolve_verification_request(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        return TrustRegistryVerificationRequestResolutionResponse(
            verification_request_public_id=verification_request_public_id,
            registry_record_public_id=payload.registry_record_public_id,
            resolution_state=TrustRegistryResolutionState.RESOLVED,
            resolution_method=payload.resolution_method.value,
            resolution_confidence=float(payload.resolution_confidence) if payload.resolution_confidence is not None else None,
            resolution_metadata=payload.resolution_metadata,
        )

    async def create_record_and_resolve_verification_request(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        return TrustRegistryVerificationRequestResolutionResponse(
            verification_request_public_id=verification_request_public_id,
            registry_record_public_id=uuid4(),
            resolution_state=TrustRegistryResolutionState.RESOLVED,
            resolution_method=payload.resolution_method.value,
            resolution_confidence=float(payload.resolution_confidence) if payload.resolution_confidence is not None else None,
            resolution_metadata=payload.resolution_metadata,
        )

    async def defer_verification_request_resolution(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        return TrustRegistryVerificationRequestResolutionResponse(
            verification_request_public_id=verification_request_public_id,
            registry_record_public_id=None,
            resolution_state=TrustRegistryResolutionState.DEFERRED,
            resolution_method=None,
            resolution_confidence=None,
            resolution_metadata=payload.resolution_metadata,
        )


async def _override_current_user() -> CurrentUser:
    return CurrentUser(
        id=UUID("00000000-0000-0000-0000-000000000999"),
        email="reviewer@kairo.test",
        role="hr",
    )


@pytest.mark.asyncio
async def test_admin_review_registry_routes_return_resolution_payloads() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_trust_registry_resolution_service] = lambda: FakeTrustRegistryResolutionService()

    transport = ASGITransport(app=app)
    request_public_id = uuid4()
    registry_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resolve_response = await client.post(
            f"/api/v1/admin/verification-requests/{request_public_id}/resolve-registry",
            json={
                "registry_record_public_id": str(registry_public_id),
                "resolution_method": "manual",
                "resolution_confidence": 95,
                "resolution_metadata": {"reason": "admin matched official identifier"},
            },
        )
        create_response = await client.post(
            f"/api/v1/admin/verification-requests/{request_public_id}/create-registry-record",
            json={
                "record": {
                    "legal_name": "Kairo Labs Pvt Ltd",
                    "display_name": "Kairo Labs",
                    "organization_type": "employer",
                    "country": "IN",
                    "state_province": "DL",
                    "website": "https://kairo.example.com",
                    "lifecycle_status": "active",
                    "trust_status": "trusted",
                    "registry_confidence_score": 92,
                    "trust_metadata": {},
                },
                "resolution_method": "created_new",
                "resolution_confidence": 92,
                "resolution_metadata": {"reason": "new authority created during review"},
            },
        )
        defer_response = await client.post(
            f"/api/v1/admin/verification-requests/{request_public_id}/defer-registry-resolution",
            json={"resolution_metadata": {"reason": "awaiting external clarification"}},
        )

    app.dependency_overrides.clear()
    assert resolve_response.status_code == 200
    assert resolve_response.json()["resolution_state"] == "resolved"
    assert create_response.status_code == 200
    assert create_response.json()["resolution_method"] == "created_new"
    assert defer_response.status_code == 200
    assert defer_response.json()["resolution_state"] == "deferred"
