"""Canonical owner-facing Trust Passport endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.dependencies.auth import CurrentUser, get_current_user, require_roles
from app.api.dependencies.services import get_passport_engine_service, get_passport_pdf_service
from app.core.constants import Role
from app.schemas.api_errors import ApiErrorResponse
from app.schemas.passport_engine import OwnerPassportResponse
from app.services.passport_engine_service import PassportEngineService
from app.services.passport_pdf_service import PDF_MEDIA_TYPE, PassportPDFService

router = APIRouter(prefix="/passport", tags=["passport"])
require_candidate = require_roles(Role.USER.value)


@router.get("/me", response_model=OwnerPassportResponse)
async def get_my_passport(
    current: CurrentUser = Depends(get_current_user),
    service: PassportEngineService = Depends(get_passport_engine_service),
) -> OwnerPassportResponse:
    return await service.get_owner_passport(current.id)


@router.get(
    "/me/pdf",
    response_class=Response,
    summary="Export the current candidate's Trust Passport as PDF",
    responses={
        200: {
            "description": "Backend-authored owner Trust Passport PDF",
            "content": {
                "application/pdf": {
                    "schema": {"type": "string", "format": "binary"},
                }
            },
        },
        401: {"model": ApiErrorResponse, "description": "Unauthorized"},
        403: {"model": ApiErrorResponse, "description": "Candidate access required"},
        404: {"model": ApiErrorResponse, "description": "Trust Passport not found"},
        429: {"model": ApiErrorResponse, "description": "Rate limited"},
        500: {"model": ApiErrorResponse, "description": "PDF generation failed"},
        503: {"model": ApiErrorResponse, "description": "PDF generation unavailable"},
    },
)
async def get_my_passport_pdf(
    current: Annotated[CurrentUser, Depends(require_candidate)],
    service: Annotated[PassportPDFService, Depends(get_passport_pdf_service)],
) -> Response:
    document = await service.generate(current.id)
    return Response(
        content=document.content,
        media_type=PDF_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{document.filename}"',
            "Cache-Control": "private, no-store",
        },
    )
