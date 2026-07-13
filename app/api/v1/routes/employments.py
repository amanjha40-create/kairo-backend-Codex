"""Applicant employment verification cases — CRUD and workflow endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_employment_service, get_verification_request_service
from app.schemas.employment import (
    AuditEventListResponse,
    AuditEventResponse,
    EmploymentCancelResponse,
    EmploymentCreate,
    EmploymentDetail,
    EmploymentPublic,
    EmploymentSubmitResponse,
    EmploymentUpdate,
)
from app.schemas.pagination import Page, PageParams
from app.services.employment_service import EmploymentService
from app.services.verification_request_service import VerificationRequestService
from app.schemas.verification_request import EmploymentVerificationDraftRequest, VerificationRequestResponse

router = APIRouter(prefix="/employments", tags=["employments"])


@router.get("/", response_model=Page[EmploymentPublic])
async def list_my_employments(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    page: Annotated[PageParams, Depends()],
    employment_service: Annotated[EmploymentService, Depends(get_employment_service)],
    statuses: Annotated[list[str] | None, Query(description="Filter by verification status")] = None,
    employer: Annotated[str | None, Query(max_length=200)] = None,
) -> Page[EmploymentPublic]:
    """Paginated list of cases created by the authenticated principal."""

    return await employment_service.list_owned(
        current.id,
        offset=page.offset,
        limit=page.limit,
        statuses=statuses,
        employer_ilike=employer,
    )


@router.post("/", response_model=EmploymentPublic, status_code=status.HTTP_201_CREATED)
async def create_employment(
    payload: EmploymentCreate,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    employment_service: Annotated[EmploymentService, Depends(get_employment_service)],
) -> EmploymentPublic:
    return await employment_service.create(current.id, payload)


@router.get("/{employment_id}", response_model=EmploymentDetail)
async def get_employment(
    employment_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    employment_service: Annotated[EmploymentService, Depends(get_employment_service)],
) -> EmploymentDetail:
    return await employment_service.get_detail_owned(current.id, employment_id)


@router.post(
    "/{employment_id}/verification-request",
    response_model=VerificationRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_employment_verification_request(
    employment_id: UUID,
    payload: EmploymentVerificationDraftRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    verification_service: Annotated[VerificationRequestService, Depends(get_verification_request_service)],
) -> VerificationRequestResponse:
    return await verification_service.create_employment_verification_draft(current.id, employment_id, payload)


@router.get("/{employment_id}/verification-request", response_model=VerificationRequestResponse)
async def get_employment_verification_request(
    employment_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    verification_service: Annotated[VerificationRequestService, Depends(get_verification_request_service)],
) -> VerificationRequestResponse:
    return await verification_service.get_employment_verification_request(current.id, employment_id)


@router.patch("/{employment_id}", response_model=EmploymentPublic)
async def update_employment(
    employment_id: UUID,
    payload: EmploymentUpdate,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    employment_service: Annotated[EmploymentService, Depends(get_employment_service)],
) -> EmploymentPublic:
    return await employment_service.update(current.id, employment_id, payload)


@router.post("/{employment_id}/submit", response_model=EmploymentSubmitResponse)
async def submit_employment(
    employment_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    employment_service: Annotated[EmploymentService, Depends(get_employment_service)],
) -> EmploymentSubmitResponse:
    return await employment_service.submit(current.id, employment_id)


@router.post("/{employment_id}/cancel", response_model=EmploymentCancelResponse)
async def cancel_employment(
    employment_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    employment_service: Annotated[EmploymentService, Depends(get_employment_service)],
) -> EmploymentCancelResponse:
    return await employment_service.cancel(current.id, employment_id)


@router.delete("/{employment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_employment(
    employment_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    employment_service: Annotated[EmploymentService, Depends(get_employment_service)],
) -> None:
    """Soft-delete a draft or additional-information case (evidence rows are soft-deleted)."""

    await employment_service.delete_owned(current.id, employment_id)


@router.get("/{employment_id}/audit-events", response_model=AuditEventListResponse)
async def list_audit_events(
    employment_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    employment_service: Annotated[EmploymentService, Depends(get_employment_service)],
    page: Annotated[PageParams, Depends()],
) -> AuditEventListResponse:
    """Verification timeline — shows who approved/reviewed (HR vs admin) and when."""

    items, total = await employment_service.list_audit_events_owned(
        current.id, employment_id, offset=page.offset, limit=page.limit,
    )
    return AuditEventListResponse(
        items=[AuditEventResponse.model_validate(i) for i in items],
        total=total,
        offset=page.offset,
        limit=page.limit,
    )
