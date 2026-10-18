"""New read surfaces must not be accessible to external principals."""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.deps import CurrentUser, get_current_user
from app.main import app


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [None, "user", "hr", "institution"])
async def test_admin_read_permission_boundaries(role):
    org, person, record = uuid4(), uuid4(), uuid4()
    base = f"/api/v1/admin/operations/organizations/{org}"
    paths = [
        f"{base}/provisioning",
        f"{base}/people/{person}/court-checks",
        f"{base}/people/{person}/court-checks/{record}",
        f"{base}/people/{person}/in-person-verifications",
        f"{base}/people/{person}/in-person-verifications/{record}",
        f"/api/v1/admin/organizations/{org}/people/{person}/verification-report",
    ]
    if role is not None:
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=uuid4(), email="synthetic@example.test", role=role
        )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for path in paths:
                response = await client.get(path)
                assert response.status_code == (401 if role is None else 403), path
    finally:
        app.dependency_overrides.pop(get_current_user, None)
