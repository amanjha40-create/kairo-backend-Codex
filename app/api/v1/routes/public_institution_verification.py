"""Public institution verification routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies.services import get_public_institution_verification_service
from app.schemas.public_institution_verification import (
    PublicInstitutionVerificationClarificationRequest,
    PublicInstitutionVerificationConfirmRequest,
    PublicInstitutionVerificationDiscrepancyRequest,
    PublicInstitutionVerificationReadResponse,
)
from app.services.public_institution_verification_service import (
    PublicInstitutionVerificationService,
)

router = APIRouter(
    prefix="/public/institution-verifications",
    tags=["public-institution-verification"],
)


@router.get(
    "/{token}",
    response_model=PublicInstitutionVerificationReadResponse,
    operation_id="getPublicInstitutionVerification",
)
async def get_public_institution_verification(
    token: str,
    service: Annotated[
        PublicInstitutionVerificationService,
        Depends(get_public_institution_verification_service),
    ],
) -> PublicInstitutionVerificationReadResponse:
    return await service.get_public_request(token)


@router.post(
    "/{token}/confirm",
    response_model=PublicInstitutionVerificationReadResponse,
    operation_id="confirmPublicInstitutionVerification",
)
async def confirm_public_institution_verification(
    token: str,
    payload: PublicInstitutionVerificationConfirmRequest,
    service: Annotated[
        PublicInstitutionVerificationService,
        Depends(get_public_institution_verification_service),
    ],
) -> PublicInstitutionVerificationReadResponse:
    return await service.confirm_from_public(token, payload)


@router.post(
    "/{token}/report-discrepancy",
    response_model=PublicInstitutionVerificationReadResponse,
    operation_id="reportPublicInstitutionVerificationDiscrepancy",
)
async def report_public_institution_verification_discrepancy(
    token: str,
    payload: PublicInstitutionVerificationDiscrepancyRequest,
    service: Annotated[
        PublicInstitutionVerificationService,
        Depends(get_public_institution_verification_service),
    ],
) -> PublicInstitutionVerificationReadResponse:
    return await service.report_discrepancy_from_public(token, payload)


@router.post(
    "/{token}/request-clarification",
    response_model=PublicInstitutionVerificationReadResponse,
    operation_id="requestPublicInstitutionVerificationClarification",
)
async def request_public_institution_verification_clarification(
    token: str,
    payload: PublicInstitutionVerificationClarificationRequest,
    service: Annotated[
        PublicInstitutionVerificationService,
        Depends(get_public_institution_verification_service),
    ],
) -> PublicInstitutionVerificationReadResponse:
    return await service.request_clarification_from_public(token, payload)
