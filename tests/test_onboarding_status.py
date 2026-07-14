"""Route-contract test for the onboarding status endpoint."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_passport_engine_service
from app.main import app
from app.schemas.passport_engine import OnboardingStatusResponse
from app.services.passport_engine_service import PassportEngineService


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


def _user(**overrides):  # noqa: ANN003, ANN202
    values = {
        "full_name": "Kairo Candidate",
        "phone": "+919876543210",
        "headline": "Software Engineer",
        "current_role": "Senior Engineer",
        "industry": "Technology",
        "years_of_experience": 5,
        "email_verified_at": datetime.now(tz=UTC),
        "phone_verified_at": datetime.now(tz=UTC),
        "employment_onboarding_completed_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _service() -> PassportEngineService:
    return PassportEngineService.__new__(PassportEngineService)


@pytest.mark.asyncio
async def test_incomplete_profile_remains_on_complete_profile_step() -> None:
    status = await _service()._build_onboarding_status(_user(headline=None))

    assert status.current_step == "complete_profile"
    assert status.passport_ready is False
    assert status.is_onboarding_complete is False
    assert status.completion_percentage < 100
    assert "headline" in status.missing_requirements


@pytest.mark.asyncio
async def test_incomplete_identity_remains_on_verify_identity_step() -> None:
    status = await _service()._build_onboarding_status(_user(phone_verified_at=None))

    assert status.current_step == "verify_identity"
    assert status.passport_ready is False
    assert status.is_onboarding_complete is False
    assert "verify_phone" in status.missing_requirements


@pytest.mark.asyncio
async def test_completed_profile_returns_canonical_passport_ready_state() -> None:
    status = await _service()._build_onboarding_status(_user())

    assert status.current_step == "complete"
    assert status.passport_ready is True
    assert status.is_onboarding_complete is True
    assert status.completion_percentage == 100
    assert status.missing_requirements == []
    assert status.next_recommended_step is None


@pytest.mark.asyncio
async def test_legacy_completion_timestamp_cannot_create_contradictory_state() -> None:
    status = await _service()._build_onboarding_status(
        _user(phone=None, employment_onboarding_completed_at=datetime.now(tz=UTC))
    )

    assert status.current_step == "complete_profile"
    assert status.passport_ready is False
    assert status.is_onboarding_complete is False
    assert status.completion_percentage < 100
    assert "phone" in status.missing_requirements
