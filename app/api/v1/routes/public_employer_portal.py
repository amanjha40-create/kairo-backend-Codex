"""Public JSON contracts for the account-free employer verification portal."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies.services import get_employer_verification_service
from app.schemas.employer_verification import (
    EmployerDecisionBody,
    EmployerPortalActionResponse,
    EmployerPortalWorkspace,
    EmployerVerifyBody,
)
from app.services.employer_verification_service import EmployerVerificationService

router = APIRouter(prefix="/public/employer-verifications", tags=["public-employer-verification"])


@router.get("/{token}", response_model=EmployerPortalWorkspace, operation_id="getEmployerVerificationWorkspace")
async def get_workspace(
    token: str,
    service: Annotated[EmployerVerificationService, Depends(get_employer_verification_service)],
) -> EmployerPortalWorkspace:
    return await service.get_portal_workspace(token)


@router.post("/{token}/verify", response_model=EmployerPortalActionResponse, operation_id="verifyEmployment")
async def verify_employment(
    token: str,
    payload: EmployerVerifyBody,
    service: Annotated[EmployerVerificationService, Depends(get_employer_verification_service)],
) -> EmployerPortalActionResponse:
    return await service.verify_from_portal(token, payload)


@router.post("/{token}/reject", response_model=EmployerPortalActionResponse, operation_id="rejectEmployment")
async def reject_employment(
    token: str,
    payload: EmployerDecisionBody,
    service: Annotated[EmployerVerificationService, Depends(get_employer_verification_service)],
) -> EmployerPortalActionResponse:
    return await service.reject_from_portal(token, payload)


@router.post(
    "/{token}/request-clarification",
    response_model=EmployerPortalActionResponse,
    operation_id="requestEmploymentClarification",
)
async def request_clarification(
    token: str,
    payload: EmployerDecisionBody,
    service: Annotated[EmployerVerificationService, Depends(get_employer_verification_service)],
) -> EmployerPortalActionResponse:
    return await service.request_clarification_from_portal(token, payload)
