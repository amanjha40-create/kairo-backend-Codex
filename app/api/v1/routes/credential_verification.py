"""Authenticated credential confirmation requests — internship & freelance magic-link email."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_credential_verification_service
from app.employment.enums import CredentialSubjectType
from app.schemas.credential_verification import (
    CredentialVerificationRequestBody,
    CredentialVerificationRequestResponse,
)
from app.services.credential_verification_service import CredentialVerificationService

router = APIRouter(tags=["credential-verification"])


@router.post(
    "/internships/{item_id}/verification/request",
    response_model=CredentialVerificationRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_internship_verification(
    item_id: UUID,
    payload: CredentialVerificationRequestBody,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[CredentialVerificationService, Depends(get_credential_verification_service)],
) -> CredentialVerificationRequestResponse:
    return await service.request_verification(
        current.id, CredentialSubjectType.INTERNSHIP.value, item_id, payload,
    )


@router.post(
    "/freelance-contracts/{item_id}/verification/request",
    response_model=CredentialVerificationRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_freelance_verification(
    item_id: UUID,
    payload: CredentialVerificationRequestBody,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[CredentialVerificationService, Depends(get_credential_verification_service)],
) -> CredentialVerificationRequestResponse:
    return await service.request_verification(
        current.id, CredentialSubjectType.FREELANCE_CONTRACT.value, item_id, payload,
    )
