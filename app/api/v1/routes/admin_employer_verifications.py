"""Read-only Admin contracts for employer outreach records."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies.services import get_employer_verification_service
from app.api.dependencies.verification_admin import CurrentUser, require_reviewer, require_view_cases
from app.schemas.employer_verification import AdminEmployerVerificationResponse
from app.services.employer_verification_service import EmployerVerificationService

router = APIRouter(prefix="/admin/employer-verifications", tags=["admin-review-workflow"])


@router.get("/{employer_verification_public_id}", response_model=AdminEmployerVerificationResponse)
async def get_admin_employer_verification(
    employer_verification_public_id: UUID,
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    svc: Annotated[EmployerVerificationService, Depends(get_employer_verification_service)],
) -> AdminEmployerVerificationResponse:
    return await svc.get_admin_summary(employer_verification_public_id)


@router.post("/{employer_verification_public_id}/revoke", response_model=AdminEmployerVerificationResponse)
async def revoke_admin_employer_verification(
    employer_verification_public_id: UUID,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    svc: Annotated[EmployerVerificationService, Depends(get_employer_verification_service)],
) -> AdminEmployerVerificationResponse:
    return await svc.revoke(employer_verification_public_id, reviewer.id)
