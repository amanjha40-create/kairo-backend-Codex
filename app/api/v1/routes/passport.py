"""Canonical owner-facing Trust Passport endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_passport_engine_service
from app.schemas.passport_engine import OwnerPassportResponse
from app.services.passport_engine_service import PassportEngineService

router = APIRouter(prefix="/passport", tags=["passport"])


@router.get("/me", response_model=OwnerPassportResponse)
async def get_my_passport(
    current: CurrentUser = Depends(get_current_user),
    service: PassportEngineService = Depends(get_passport_engine_service),
) -> OwnerPassportResponse:
    return await service.get_owner_passport(current.id)
