"""API-level error contract tests for shared envelopes."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_organization_service
from app.main import app


class _NoopOrganizationService:
    async def list_my_organizations(self, actor_user_id, params=None):  # noqa: ANN001
        return []


async def _override_current_user() -> CurrentUser:
    return CurrentUser(id=uuid4(), email="owner@example.com", role="user")


@pytest.mark.asyncio
async def test_unauthorized_errors_use_shared_envelope() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/users/me")

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "unauthorized"
    assert "message" in body["error"]


@pytest.mark.asyncio
async def test_validation_errors_use_normalized_detail_structure() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_service] = lambda: _NoopOrganizationService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/organizations/me?page=0")

    app.dependency_overrides.clear()
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"][0]["location"][-1] == "page"
    assert "message" in body["error"]["details"][0]
    assert "error_type" in body["error"]["details"][0]
