from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_resume_review_service
from app.resumes.review_schemas import (
    ImportBatchResponse,
    ReviewImportRequest,
    ReviewItemResponse,
    ReviewItemUpdateRequest,
    ReviewPlanResponse,
    ReviewSessionResponse,
    ReviewSessionUpdateRequest,
    ReviewValidateRequest,
)
from app.services.resume_review_service import ResumeReviewService

resume_router = APIRouter(prefix="/resumes", tags=["resume review"])
router = APIRouter(prefix="/resume-reviews", tags=["resume review"])


@resume_router.post("/{resume_id}/review-session", response_model=ReviewSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_review_session(resume_id: UUID, current: Annotated[CurrentUser, Depends(get_current_user)], service: Annotated[ResumeReviewService, Depends(get_resume_review_service)]) -> ReviewSessionResponse:
    """Create or return the durable candidate review for a parsed, unverified resume."""
    return await service.create(current.id, resume_id)


@resume_router.get("/{resume_id}/review-session", response_model=ReviewSessionResponse)
async def get_resume_review_session(resume_id: UUID, current: Annotated[CurrentUser, Depends(get_current_user)], service: Annotated[ResumeReviewService, Depends(get_resume_review_service)]) -> ReviewSessionResponse:
    return await service.get_by_resume(current.id, resume_id)


@router.get("/{review_id}", response_model=ReviewSessionResponse)
async def get_review(review_id: UUID, current: Annotated[CurrentUser, Depends(get_current_user)], service: Annotated[ResumeReviewService, Depends(get_resume_review_service)]) -> ReviewSessionResponse:
    return await service.get(current.id, review_id)


@router.patch("/{review_id}", response_model=ReviewSessionResponse)
async def update_review(review_id: UUID, payload: ReviewSessionUpdateRequest, current: Annotated[CurrentUser, Depends(get_current_user)], service: Annotated[ResumeReviewService, Depends(get_resume_review_service)]) -> ReviewSessionResponse:
    return await service.update_session(current.id, review_id, payload)


@router.patch("/{review_id}/items/{item_id}", response_model=ReviewItemResponse)
async def update_review_item(review_id: UUID, item_id: UUID, payload: ReviewItemUpdateRequest, current: Annotated[CurrentUser, Depends(get_current_user)], service: Annotated[ResumeReviewService, Depends(get_resume_review_service)]) -> ReviewItemResponse:
    """Edit/select one claim and re-run deterministic duplicate matching."""
    return await service.update_item(current.id, review_id, item_id, payload)


@router.post("/{review_id}/validate", response_model=ReviewPlanResponse)
async def validate_review(review_id: UUID, payload: ReviewValidateRequest, current: Annotated[CurrentUser, Depends(get_current_user)], service: Annotated[ResumeReviewService, Depends(get_resume_review_service)]) -> ReviewPlanResponse:
    """Return the explicit import plan without mutating Career records."""
    return await service.validate(current.id, review_id, payload)


@router.post("/{review_id}/import", response_model=ImportBatchResponse, status_code=status.HTTP_201_CREATED)
async def import_review(review_id: UUID, payload: ReviewImportRequest, current: Annotated[CurrentUser, Depends(get_current_user)], service: Annotated[ResumeReviewService, Depends(get_resume_review_service)]) -> ImportBatchResponse:
    """Import only candidate-confirmed claims; records remain unverified."""
    return await service.import_review(current.id, review_id, payload)


@router.get("/{review_id}/imports/{batch_id}", response_model=ImportBatchResponse)
async def get_import_status(review_id: UUID, batch_id: UUID, current: Annotated[CurrentUser, Depends(get_current_user)], service: Annotated[ResumeReviewService, Depends(get_resume_review_service)]) -> ImportBatchResponse:
    return await service.import_status(current.id, review_id, batch_id)


@router.get("/{review_id}/import-status", response_model=ImportBatchResponse)
async def get_latest_import_status(review_id: UUID, current: Annotated[CurrentUser, Depends(get_current_user)], service: Annotated[ResumeReviewService, Depends(get_resume_review_service)]) -> ImportBatchResponse:
    return await service.latest_import_status(current.id, review_id)


@router.post("/{review_id}/cancel", response_model=ReviewSessionResponse)
async def cancel_review(review_id: UUID, current: Annotated[CurrentUser, Depends(get_current_user)], service: Annotated[ResumeReviewService, Depends(get_resume_review_service)]) -> ReviewSessionResponse:
    return await service.cancel(current.id, review_id)
