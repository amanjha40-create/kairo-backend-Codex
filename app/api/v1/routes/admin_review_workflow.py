"""Generic admin review routes for verification requests."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies.services import (
    get_trust_registry_resolution_service,
    get_verification_request_admin_review_service,
)
from app.api.dependencies.verification_admin import (
    CurrentUser,
    require_assign,
    require_remark,
    require_request_more_info,
    require_reviewer,
    require_view_cases,
)
from app.schemas.admin_review_workflow import (
    AdminReviewAssignRequest,
    AdminReviewCorrectionRequest,
    AdminReviewDecisionRequest,
    AdminReviewDetailResponse,
    AdminReviewNoteCreateRequest,
    AdminReviewNoteResponse,
    AdminReviewOrganizationResolutionRequest,
    AdminReviewQueueResponse,
    AdminReviewTimelineResponse,
    AdminReviewWorkflowEnvelope,
    AdminVerificationContactReviewRequest,
)
from app.schemas.pagination import ListQueryParams
from app.schemas.trust_registry import (
    TrustRegistryCreateAndResolveRequest,
    TrustRegistryDeferResolutionRequest,
    TrustRegistryResolutionRequest,
    TrustRegistryVerificationRequestResolutionResponse,
)
from app.schemas.verification_request import VerificationContactResponse, VerificationRequestResponse
from app.services.trust_registry_resolution_service import TrustRegistryResolutionService
from app.services.verification_request_admin_review_service import VerificationRequestAdminReviewService

router = APIRouter(prefix="/admin/verification-requests", tags=["admin-review-workflow"])


@router.get("/queue", response_model=AdminReviewQueueResponse)
async def get_admin_review_queue(
    params: Annotated[ListQueryParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    svc: Annotated[VerificationRequestAdminReviewService, Depends(get_verification_request_admin_review_service)],
) -> AdminReviewQueueResponse:
    return await svc.get_queue(params)


@router.get("/{verification_request_public_id}", response_model=AdminReviewDetailResponse)
async def get_admin_review_detail(
    verification_request_public_id: UUID,
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    svc: Annotated[VerificationRequestAdminReviewService, Depends(get_verification_request_admin_review_service)],
) -> AdminReviewDetailResponse:
    return await svc.get_detail(verification_request_public_id)


@router.post("/{verification_request_public_id}/assign", response_model=AdminReviewWorkflowEnvelope)
async def assign_admin_review(
    verification_request_public_id: UUID,
    payload: AdminReviewAssignRequest,
    reviewer: Annotated[CurrentUser, Depends(require_assign)],
    svc: Annotated[VerificationRequestAdminReviewService, Depends(get_verification_request_admin_review_service)],
) -> AdminReviewWorkflowEnvelope:
    return await svc.assign(reviewer.id, verification_request_public_id, payload)


@router.post("/{verification_request_public_id}/notes", response_model=AdminReviewNoteResponse)
async def add_admin_review_note(
    verification_request_public_id: UUID,
    payload: AdminReviewNoteCreateRequest,
    reviewer: Annotated[CurrentUser, Depends(require_remark)],
    svc: Annotated[VerificationRequestAdminReviewService, Depends(get_verification_request_admin_review_service)],
) -> AdminReviewNoteResponse:
    return await svc.add_note(reviewer.id, verification_request_public_id, payload)


@router.post("/{verification_request_public_id}/request-corrections", response_model=VerificationRequestResponse)
async def request_admin_review_corrections(
    verification_request_public_id: UUID,
    payload: AdminReviewCorrectionRequest,
    reviewer: Annotated[CurrentUser, Depends(require_request_more_info)],
    svc: Annotated[VerificationRequestAdminReviewService, Depends(get_verification_request_admin_review_service)],
) -> VerificationRequestResponse:
    return await svc.request_corrections(reviewer.id, verification_request_public_id, payload)


@router.post(
    "/{verification_request_public_id}/verification-contact/review",
    response_model=VerificationContactResponse,
)
async def review_verification_contact(
    verification_request_public_id: UUID,
    payload: AdminVerificationContactReviewRequest,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    svc: Annotated[VerificationRequestAdminReviewService, Depends(get_verification_request_admin_review_service)],
) -> VerificationContactResponse:
    return await svc.review_contact(reviewer.id, verification_request_public_id, payload)


@router.post("/{verification_request_public_id}/approve", response_model=VerificationRequestResponse)
async def approve_admin_review(
    verification_request_public_id: UUID,
    payload: AdminReviewDecisionRequest,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    svc: Annotated[VerificationRequestAdminReviewService, Depends(get_verification_request_admin_review_service)],
) -> VerificationRequestResponse:
    return await svc.approve(reviewer.id, verification_request_public_id, payload)


@router.post("/{verification_request_public_id}/reject", response_model=VerificationRequestResponse)
async def reject_admin_review(
    verification_request_public_id: UUID,
    payload: AdminReviewDecisionRequest,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    svc: Annotated[VerificationRequestAdminReviewService, Depends(get_verification_request_admin_review_service)],
) -> VerificationRequestResponse:
    return await svc.reject(reviewer.id, verification_request_public_id, payload)


@router.post("/{verification_request_public_id}/resolve-organization", response_model=VerificationRequestResponse)
async def resolve_admin_review_organization(
    verification_request_public_id: UUID,
    payload: AdminReviewOrganizationResolutionRequest,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    svc: Annotated[VerificationRequestAdminReviewService, Depends(get_verification_request_admin_review_service)],
) -> VerificationRequestResponse:
    return await svc.resolve_organization(reviewer.id, verification_request_public_id, payload)


@router.post(
    "/{verification_request_public_id}/resolve-registry",
    response_model=TrustRegistryVerificationRequestResolutionResponse,
)
async def resolve_admin_review_registry_record(
    verification_request_public_id: UUID,
    payload: TrustRegistryResolutionRequest,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    svc: Annotated[TrustRegistryResolutionService, Depends(get_trust_registry_resolution_service)],
) -> TrustRegistryVerificationRequestResolutionResponse:
    return await svc.resolve_verification_request(reviewer.id, verification_request_public_id, payload)


@router.post(
    "/{verification_request_public_id}/create-registry-record",
    response_model=TrustRegistryVerificationRequestResolutionResponse,
)
async def create_admin_review_registry_record(
    verification_request_public_id: UUID,
    payload: TrustRegistryCreateAndResolveRequest,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    svc: Annotated[TrustRegistryResolutionService, Depends(get_trust_registry_resolution_service)],
) -> TrustRegistryVerificationRequestResolutionResponse:
    return await svc.create_record_and_resolve_verification_request(reviewer.id, verification_request_public_id, payload)


@router.post(
    "/{verification_request_public_id}/defer-registry-resolution",
    response_model=TrustRegistryVerificationRequestResolutionResponse,
)
async def defer_admin_review_registry_resolution(
    verification_request_public_id: UUID,
    payload: TrustRegistryDeferResolutionRequest,
    reviewer: Annotated[CurrentUser, Depends(require_reviewer)],
    svc: Annotated[TrustRegistryResolutionService, Depends(get_trust_registry_resolution_service)],
) -> TrustRegistryVerificationRequestResolutionResponse:
    return await svc.defer_verification_request_resolution(reviewer.id, verification_request_public_id, payload)


@router.get("/{verification_request_public_id}/timeline", response_model=AdminReviewTimelineResponse)
async def get_admin_review_timeline(
    verification_request_public_id: UUID,
    params: Annotated[ListQueryParams, Depends()],
    _: Annotated[CurrentUser, Depends(require_view_cases)],
    svc: Annotated[VerificationRequestAdminReviewService, Depends(get_verification_request_admin_review_service)],
) -> AdminReviewTimelineResponse:
    return await svc.get_timeline(verification_request_public_id, params)
