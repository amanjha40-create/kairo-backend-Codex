"""Public Trust Passport access by share token."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies.services import get_public_passport_service
from app.schemas.public_passport import PublicPassportResponse
from app.services.public_passport_service import PublicPassportService

router = APIRouter(prefix="/public/passport", tags=["public"])


@router.get("/{token}", response_model=PublicPassportResponse)
async def get_public_passport(
    token: str,
    svc: Annotated[PublicPassportService, Depends(get_public_passport_service)],
) -> PublicPassportResponse:
    return await svc.get_by_token(token)
