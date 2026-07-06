"""Public Trust Passport access by share token."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.dependencies.services import get_passport_share_view_service, get_public_passport_service
from app.schemas.public_passport import PublicPassportResponse
from app.services.public_passport_service import PublicPassportService
from app.services.passport_share_view_service import PassportShareViewService

router = APIRouter(prefix="/public/passport", tags=["public"])


@router.get("/{token}", response_model=PublicPassportResponse)
async def get_public_passport(
    token: str,
    request: Request,
    svc: Annotated[PublicPassportService, Depends(get_public_passport_service)],
    views: Annotated[PassportShareViewService, Depends(get_passport_share_view_service)],
) -> PublicPassportResponse:
    response = await svc.get_by_token(token)
    viewer_ip = request.client.host if request.client else "unknown"
    await views.record_successful_view(
        share_id=response.share.id,
        viewer_ip=viewer_ip,
        user_agent=request.headers.get("user-agent"),
        referrer=request.headers.get("referer"),
    )
    return response
