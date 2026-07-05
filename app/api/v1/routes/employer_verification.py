"""Authenticated employer confirmation request — sends magic-link email."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_employer_verification_service
from app.schemas.employer_verification import (
    EmployerVerificationRequestBody,
    EmployerVerificationRequestResponse,
)
from app.services.employer_verification_service import EmployerVerificationService

router = APIRouter(prefix="/employments", tags=["employer-verification"])


@router.post(
    "/{employment_id}/employer-verification/request",
    response_model=EmployerVerificationRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_employer_verification(
    employment_id: UUID,
    payload: EmployerVerificationRequestBody,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[EmployerVerificationService, Depends(get_employer_verification_service)],
) -> EmployerVerificationRequestResponse:
    """Email the employer contact with confirm / decline links (no documents required)."""

    return await service.request_verification(current.id, employment_id, payload)
