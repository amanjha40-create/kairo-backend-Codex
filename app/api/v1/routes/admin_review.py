"""Admin review shortcuts — queue listing, approve, reject."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies.services import get_admin_verification_service
from app.api.dependencies.verification_admin import CurrentUser, require_reviewer, require_view_cases
from app.employment.enums import VerificationStatus
from app.schemas.employment import (
    AdminVerificationTransitionRequest,
    EmploymentDetail,
    EmploymentPublic,
)
from app.schemas.employment.requests import AdminRejectRequest, AdminVerifyRequest
from app.schemas.pagination import Page, PageParams
from app.services.admin_verification_service import AdminVerificationService

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/review-queue", response_model=Page[EmploymentPublic])
async def get_review_queue(
    page: Annotated[PageParams, Depends()],
    admin_service: Annotated[AdminVerificationService, Depends(get_admin_verification_service)],
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    statuses: Annotated[list[str] | None, Query(description="Filter by verification status")] = None,
    employer: Annotated[str | None, Query(max_length=200)] = None,
    created_after: Annotated[date | None, Query()] = None,
    created_before: Annotated[date | None, Query()] = None,
) -> Page[EmploymentPublic]:
    return await admin_service.list_queue(
        offset=page.offset,
        limit=page.limit,
        statuses=statuses,
        employer_ilike=employer,
        created_after=created_after,
        created_before=created_before,
    )


@router.post("/verify", response_model=EmploymentDetail)
async def verify_employment(
    payload: AdminVerifyRequest,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    admin_service: Annotated[AdminVerificationService, Depends(get_admin_verification_service)],
) -> EmploymentDetail:
    transition = AdminVerificationTransitionRequest(
        new_status=VerificationStatus.APPROVED,
        summary=payload.summary,
    )
    return await admin_service.transition(reviewer.id, payload.employment_id, transition)


@router.post("/reject", response_model=EmploymentDetail)
async def reject_employment(
    payload: AdminRejectRequest,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    admin_service: Annotated[AdminVerificationService, Depends(get_admin_verification_service)],
) -> EmploymentDetail:
    transition = AdminVerificationTransitionRequest(
        new_status=VerificationStatus.REJECTED,
        summary=payload.summary,
    )
    return await admin_service.transition(reviewer.id, payload.employment_id, transition)
