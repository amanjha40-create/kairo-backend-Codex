"""Route-contract test for the onboarding status endpoint."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_passport_engine_service
from app.main import app
from app.schemas.passport_engine import OnboardingStatusResponse


class FakePassportEngineService:
    async def get_onboarding_status(self, user_id) -> OnboardingStatusResponse:  # noqa: ANN001
        return OnboardingStatusResponse(
            completed_steps=["verify_email", "complete_profile"],
            missing_requirements=["add_employment_or_work_history", "add_education"],
            next_recommended_step="add_employment_or_work_history",
            completion_percentage=40,
            is_onboarding_complete=False,
        )


async def _override_current_user() -> CurrentUser:
    return CurrentUser(id=uuid4(), email="owner@example.com", role="user")


@pytest.mark.asyncio
async def test_get_onboarding_status_returns_backend_owned_progress() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_passport_engine_service] = lambda: FakePassportEngineService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/onboarding/status")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["completed_steps"] == ["verify_email", "complete_profile"]
    assert body["next_recommended_step"] == "add_employment_or_work_history"
    assert body["completion_percentage"] == 40
