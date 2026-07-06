"""Canonical onboarding status endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_passport_engine_service
from app.schemas.passport_engine import OnboardingStatusResponse
from app.services.passport_engine_service import PassportEngineService

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.get("/status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(
    current: CurrentUser = Depends(get_current_user),
    service: PassportEngineService = Depends(get_passport_engine_service),
) -> OnboardingStatusResponse:
    return await service.get_onboarding_status(current.id)
