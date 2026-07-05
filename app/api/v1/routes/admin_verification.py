"""Reviewer queue — JWT authentication + verification RBAC (`VERIFICATION_REVIEW_ROLES`)."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.dependencies.services import get_admin_verification_service
from app.api.dependencies.verification_admin import (
    CurrentUser,
    require_assign,
    require_remark,
    require_reviewer,
    require_view_cases,
)
from app.schemas.admin_verification import VerificationAuditEntryPublic
from app.schemas.employment import (
    AddRemarkRequest,
    AdminDecisionSummaryBody,
    AdminDocumentDecisionBody,
    AdminDocumentRejectBody,
    AdminVerificationTransitionRequest,
    AssignReviewRequest,
    EmploymentDetail,
    EmploymentDocumentResponse,
    EmploymentPublic,
)
from app.schemas.pagination import Page, PageParams
from app.services.admin_verification_service import AdminVerificationService

router = APIRouter(prefix="/admin/verifications", tags=["admin-verifications"])


@router.get("/queue", response_model=Page[EmploymentPublic])
async def list_verification_queue(
    page: Annotated[PageParams, Depends()],
    admin_service: Annotated[AdminVerificationService, Depends(get_admin_verification_service)],
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    statuses: Annotated[list[str] | None, Query(description="Filter by verification status")] = None,
    employer: Annotated[str | None, Query(max_length=200)] = None,
    created_after: Annotated[date | None, Query()] = None,
    created_before: Annotated[date | None, Query()] = None,
) -> Page[EmploymentPublic]:
    """Operational listing — indexed filters for triage consoles."""

    return await admin_service.list_queue(
        offset=page.offset,
        limit=page.limit,
        statuses=statuses,
        employer_ilike=employer,
        created_after=created_after,
        created_before=created_before,
    )


@router.get("/{employment_id}/history", response_model=Page[VerificationAuditEntryPublic])
async def verification_history(
    employment_id: UUID,
    page: Annotated[PageParams, Depends()],
    admin_service: Annotated[AdminVerificationService, Depends(get_admin_verification_service)],
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    order: Annotated[Literal["asc", "desc"], Query(description="Sort audit rows by created_at")] = "desc",
) -> Page[VerificationAuditEntryPublic]:
    """Immutable verification audit trail for compliance review."""

    return await admin_service.list_verification_history(
        employment_id,
        offset=page.offset,
        limit=page.limit,
        order=order,
    )


@router.get("/{employment_id}", response_model=EmploymentDetail)
async def admin_get_employment(
    employment_id: UUID,
    admin_service: Annotated[AdminVerificationService, Depends(get_admin_verification_service)],
    _: Annotated[CurrentUser, Depends(require_view_cases)],
) -> EmploymentDetail:
    return await admin_service.get_detail(employment_id)


@router.post("/{employment_id}/assign", response_model=EmploymentDetail)
async def assign_review(
    employment_id: UUID,
    payload: AssignReviewRequest,
    reviewer: Annotated[CurrentUser, Depends(require_assign)],
    admin_service: Annotated[AdminVerificationService, Depends(get_admin_verification_service)],
) -> EmploymentDetail:
    """Assign or reassign reviewer — optional automatic transition submitted → under_review."""

    return await admin_service.assign_review(
        reviewer.id,
        employment_id,
        assignee_user_id=payload.assignee_user_id,
        start_review=payload.start_review,
    )


@router.post(
    "/{employment_id}/documents/{document_id}/approve",
    response_model=EmploymentDocumentResponse,
)
async def approve_document(
    employment_id: UUID,
    document_id: UUID,
    payload: AdminDocumentDecisionBody,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    admin_service: Annotated[AdminVerificationService, Depends(get_admin_verification_service)],
) -> EmploymentDocumentResponse:
    """Approve one uploaded document — case approval requires every document approved."""

    return await admin_service.approve_document(
        reviewer.id,
        employment_id,
        document_id,
        note=payload.note,
    )


@router.post(
    "/{employment_id}/documents/{document_id}/reject",
    response_model=EmploymentDocumentResponse,
)
async def reject_document(
    employment_id: UUID,
    document_id: UUID,
    payload: AdminDocumentRejectBody,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    admin_service: Annotated[AdminVerificationService, Depends(get_admin_verification_service)],
) -> EmploymentDocumentResponse:
    """Reject one document with a note — blocks case-level approval until resolved."""

    return await admin_service.reject_document(
        reviewer.id,
        employment_id,
        document_id,
        note=payload.note,
    )


@router.post("/{employment_id}/approve", response_model=EmploymentDetail)
async def approve_verification(
    employment_id: UUID,
    payload: AdminDecisionSummaryBody,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    admin_service: Annotated[AdminVerificationService, Depends(get_admin_verification_service)],
) -> EmploymentDetail:
    """Approve — audited status transition with required summary."""

    return await admin_service.approve_verification(
        reviewer.id,
        employment_id,
        summary=payload.summary,
    )


@router.post("/{employment_id}/reject", response_model=EmploymentDetail)
async def reject_verification(
    employment_id: UUID,
    payload: AdminDecisionSummaryBody,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    admin_service: Annotated[AdminVerificationService, Depends(get_admin_verification_service)],
) -> EmploymentDetail:
    """Reject — audited status transition with required summary."""

    return await admin_service.reject_verification(
        reviewer.id,
        employment_id,
        summary=payload.summary,
    )


@router.post("/{employment_id}/remarks", response_model=EmploymentDetail)
async def add_verification_remark(
    employment_id: UUID,
    payload: AddRemarkRequest,
    reviewer: Annotated[CurrentUser, Depends(require_remark)],
    admin_service: Annotated[AdminVerificationService, Depends(get_admin_verification_service)],
) -> EmploymentDetail:
    """Append-only reviewer remark — does not change verification status."""

    return await admin_service.add_remark(
        reviewer.id,
        employment_id,
        remark=payload.remark,
    )


@router.post("/{employment_id}/transition", response_model=EmploymentDetail)
async def transition_employment(
    employment_id: UUID,
    payload: AdminVerificationTransitionRequest,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    admin_service: Annotated[AdminVerificationService, Depends(get_admin_verification_service)],
) -> EmploymentDetail:
    """Audited workflow transition — restricted legal states enforced server-side."""

    return await admin_service.transition(reviewer.id, employment_id, payload)
