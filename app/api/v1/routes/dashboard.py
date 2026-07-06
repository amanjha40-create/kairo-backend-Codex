"""Backend-owned dashboard summary endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_passport_engine_service
from app.schemas.passport_engine import DashboardResponse
from app.services.passport_engine_service import PassportEngineService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
async def get_dashboard(
    current: CurrentUser = Depends(get_current_user),
    service: PassportEngineService = Depends(get_passport_engine_service),
) -> DashboardResponse:
    return await service.get_dashboard(current.id)
