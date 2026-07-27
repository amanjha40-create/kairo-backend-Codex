"""Admin Portal authentication/session boundary tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.main import app


async def _admin_user() -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        email="admin@example.com",
        role="admin",
        full_name="Ada Admin",
    )


async def _superadmin_user() -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        email="superadmin@example.com",
        role="superadmin",
        full_name="Sam Superadmin",
    )


async def _candidate_user() -> CurrentUser:
    return CurrentUser(id=uuid4(), email="candidate@example.com", role="user")


@pytest.mark.asyncio
async def test_admin_session_returns_backend_role_and_permissions() -> None:
    app.dependency_overrides[get_current_user] = _admin_user
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/admin/session")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    account = response.json()["account"]
    assert account["email"] == "admin@example.com"
    assert account["name"] == "Ada Admin"
    assert account["role_key"] == "admin"
    assert account["is_active"] is True
    assert "access_admin_portal" in account["permissions"]


@pytest.mark.asyncio
async def test_superadmin_session_has_effective_permissions() -> None:
    app.dependency_overrides[get_current_user] = _superadmin_user
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/admin/session")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    permissions = response.json()["account"]["permissions"]
    assert "access_admin_portal" in permissions
    assert "assign_roles" in permissions


@pytest.mark.asyncio
async def test_admin_session_rejects_unauthenticated_request() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/admin/session")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_session_rejects_invalid_token() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/admin/session",
            headers={"Authorization": "Bearer invalid-token"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_session_rejects_authenticated_non_admin() -> None:
    app.dependency_overrides[get_current_user] = _candidate_user
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/admin/session")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
