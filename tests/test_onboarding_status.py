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
            current_step="complete_profile",
            email_verified=True,
            phone_verified=False,
            passport_ready=False,
            completed_steps=["verify_email"],
            missing_requirements=["verify_phone", "headline", "current_role"],
            next_recommended_step="complete_profile",
            completion_percentage=50,
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
    assert body["current_step"] == "complete_profile"
    assert body["email_verified"] is True
    assert body["phone_verified"] is False
    assert body["passport_ready"] is False
    assert body["completed_steps"] == ["verify_email"]
    assert body["next_recommended_step"] == "complete_profile"
    assert body["completion_percentage"] == 50
