"""Contract tests for the Admin overview projection."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.services import get_admin_overview_service
from app.auth.deps import CurrentUser, get_current_user
from app.main import app
from app.schemas.admin_overview import AdminOverviewResponse
from app.schemas.trust_safety import TrustSafetyOverviewSummaryResponse


def _overview(*, populated: bool) -> AdminOverviewResponse:
    now = datetime.now(UTC)
    return AdminOverviewResponse(
        generated_at=now,
        recent_window_days=30,
        total_verification_requests=2 if populated else 0,
        requests_by_status={"pending_admin_review": 1, "verified": 1} if populated else {},
        pending_review_count=1 if populated else 0,
        priority_case_count=1 if populated else 0,
        recent_cases=[],
        recent_admin_activity=[],
        organization_total=1 if populated else 0,
        registry_total=1 if populated else 0,
        user_total=2 if populated else 0,
        trust_safety=TrustSafetyOverviewSummaryResponse(
            open_investigations=1 if populated else 0,
            high_or_critical_investigations=1 if populated else 0,
            unassigned_investigations=0,
            active_signals=2 if populated else 0,
        ),
    )


class FakeAdminOverviewService:
    def __init__(self, *, populated: bool = True) -> None:
        self.populated = populated

    async def get_overview(self, *, recent_window_days: int) -> AdminOverviewResponse:
        response = _overview(populated=self.populated)
        return response.model_copy(update={"recent_window_days": recent_window_days})


async def _admin_user() -> CurrentUser:
    return CurrentUser(
        id=UUID("00000000-0000-0000-0000-000000000999"),
        email="admin@kairo.test",
        role="admin",
    )


async def _candidate_user() -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        email="candidate@kairo.test",
        role="user",
    )


@pytest.mark.asyncio
async def test_admin_overview_returns_empty_state_values() -> None:
    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[get_admin_overview_service] = (
        lambda: FakeAdminOverviewService(populated=False)
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/admin/overview")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["total_verification_requests"] == 0
    assert response.json()["requests_by_status"] == {}


@pytest.mark.asyncio
async def test_admin_overview_aggregates_populated_data_and_window() -> None:
    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[get_admin_overview_service] = lambda: FakeAdminOverviewService()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/admin/overview?recent_window_days=14")
    app.dependency_overrides.clear()

    body = response.json()
    assert response.status_code == 200
    assert body["recent_window_days"] == 14
    assert body["pending_review_count"] == 1
    assert body["priority_case_count"] == 1
    assert body["organization_total"] == 1
    assert body["registry_total"] == 1
    assert body["trust_safety"]["open_investigations"] == 1


@pytest.mark.asyncio
async def test_admin_overview_requires_authentication_and_permission() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        unauthenticated = await client.get("/api/v1/admin/overview")

    app.dependency_overrides[get_current_user] = _candidate_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        forbidden = await client.get("/api/v1/admin/overview")
    app.dependency_overrides.clear()

    assert unauthenticated.status_code == 401
    assert forbidden.status_code == 403
