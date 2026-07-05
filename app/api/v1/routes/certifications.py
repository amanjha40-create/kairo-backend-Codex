"""Certification routes — CRUD + optional S3 document upload."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_certification_service
from app.schemas.certification import (
    CertificationCompleteUploadRequest,
    CertificationCreateRequest,
    CertificationDownloadUrlResponse,
    CertificationResponse,
    CertificationUpdateRequest,
    CertificationUploadIntentRequest,
    CertificationUploadIntentResponse,
)
from app.schemas.pagination import Page, PageParams
from app.services.certification_service import CertificationService

router = APIRouter(prefix="/certifications", tags=["certifications"])


@router.get("", response_model=Page[CertificationResponse])
async def list_certifications(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    page: Annotated[PageParams, Depends()],
    svc: Annotated[CertificationService, Depends(get_certification_service)],
) -> Page[CertificationResponse]:
    items, total = await svc.list_for_user(current.id, offset=page.offset, limit=page.limit)
    return Page[CertificationResponse](
        items=[CertificationResponse.model_validate(i) for i in items],
        total=total, offset=page.offset, limit=page.limit,
    )


@router.post("", response_model=CertificationResponse, status_code=status.HTTP_201_CREATED)
async def create_certification(
    payload: CertificationCreateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[CertificationService, Depends(get_certification_service)],
) -> CertificationResponse:
    item = await svc.create(current.id, payload)
    return CertificationResponse.model_validate(item)


@router.post(
    "/upload-intent",
    response_model=CertificationUploadIntentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_upload_intent(
    payload: CertificationUploadIntentRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[CertificationService, Depends(get_certification_service)],
) -> CertificationUploadIntentResponse:
    return await svc.create_upload_intent(current.id, payload)


@router.post("/{certification_id}/complete-upload", response_model=CertificationResponse)
async def complete_upload(
    certification_id: UUID,
    payload: CertificationCompleteUploadRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[CertificationService, Depends(get_certification_service)],
) -> CertificationResponse:
    item = await svc.complete_upload(current.id, certification_id, payload.checksum_sha256)
    return CertificationResponse.model_validate(item)


@router.get("/{certification_id}", response_model=CertificationResponse)
async def get_certification(
    certification_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[CertificationService, Depends(get_certification_service)],
) -> CertificationResponse:
    item = await svc.get_for_user(current.id, certification_id)
    return CertificationResponse.model_validate(item)


@router.get("/{certification_id}/download-url", response_model=CertificationDownloadUrlResponse)
async def get_download_url(
    certification_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[CertificationService, Depends(get_certification_service)],
) -> CertificationDownloadUrlResponse:
    return await svc.get_download_url(current.id, certification_id)


@router.patch("/{certification_id}", response_model=CertificationResponse)
async def update_certification(
    certification_id: UUID,
    payload: CertificationUpdateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[CertificationService, Depends(get_certification_service)],
) -> CertificationResponse:
    item = await svc.update(current.id, certification_id, payload)
    return CertificationResponse.model_validate(item)


@router.delete("/{certification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_certification(
    certification_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[CertificationService, Depends(get_certification_service)],
) -> None:
    await svc.delete(current.id, certification_id)
