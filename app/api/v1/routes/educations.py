"""Education records and supporting documents."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_education_service
from app.schemas.education import (
    EducationCreateRequest,
    EducationDocumentCompleteUploadRequest,
    EducationDocumentDownloadUrlResponse,
    EducationDocumentResponse,
    EducationDocumentUploadIntentRequest,
    EducationDocumentUploadIntentResponse,
    EducationResponse,
    EducationUpdateRequest,
)
from app.schemas.pagination import Page, PageParams
from app.services.education_service import EducationService

router = APIRouter(prefix="/educations", tags=["educations"])


# --- Education CRUD ---


@router.get("", response_model=Page[EducationResponse])
async def list_my_educations(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    page: Annotated[PageParams, Depends()],
    svc: Annotated[EducationService, Depends(get_education_service)],
) -> Page[EducationResponse]:
    items, total = await svc.list_for_user(current.id, offset=page.offset, limit=page.limit)
    return Page[EducationResponse](
        items=[EducationResponse.model_validate(e) for e in items],
        total=total,
        offset=page.offset,
        limit=page.limit,
    )


@router.post("", response_model=EducationResponse, status_code=status.HTTP_201_CREATED)
async def create_education(
    payload: EducationCreateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[EducationService, Depends(get_education_service)],
) -> EducationResponse:
    edu = await svc.create(current.id, payload)
    return EducationResponse.model_validate(edu)


@router.get("/{education_id}", response_model=EducationResponse)
async def get_education(
    education_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[EducationService, Depends(get_education_service)],
) -> EducationResponse:
    edu = await svc.get_owned(current.id, education_id)
    return EducationResponse.model_validate(edu)


@router.patch("/{education_id}", response_model=EducationResponse)
async def update_education(
    education_id: UUID,
    payload: EducationUpdateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[EducationService, Depends(get_education_service)],
) -> EducationResponse:
    edu = await svc.update(current.id, education_id, payload)
    return EducationResponse.model_validate(edu)


@router.post("/{education_id}/submit", response_model=EducationResponse)
async def submit_education(
    education_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[EducationService, Depends(get_education_service)],
) -> EducationResponse:
    edu = await svc.submit(current.id, education_id)
    return EducationResponse.model_validate(edu)


@router.delete("/{education_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_education(
    education_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[EducationService, Depends(get_education_service)],
) -> None:
    await svc.delete(current.id, education_id)


# --- Education documents ---


@router.get(
    "/{education_id}/documents",
    response_model=Page[EducationDocumentResponse],
)
async def list_education_documents(
    education_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    page: Annotated[PageParams, Depends()],
    svc: Annotated[EducationService, Depends(get_education_service)],
) -> Page[EducationDocumentResponse]:
    items, total = await svc.list_documents(
        current.id, education_id, offset=page.offset, limit=page.limit,
    )
    return Page[EducationDocumentResponse](
        items=[EducationDocumentResponse.model_validate(d) for d in items],
        total=total,
        offset=page.offset,
        limit=page.limit,
    )


@router.post(
    "/{education_id}/documents/upload-intent",
    response_model=EducationDocumentUploadIntentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_education_document_upload_intent(
    education_id: UUID,
    payload: EducationDocumentUploadIntentRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[EducationService, Depends(get_education_service)],
) -> EducationDocumentUploadIntentResponse:
    return await svc.create_document_upload_intent(current.id, education_id, payload)


@router.post(
    "/{education_id}/documents/{document_id}/complete-upload",
    response_model=EducationDocumentResponse,
)
async def complete_education_document_upload(
    education_id: UUID,
    document_id: UUID,
    payload: EducationDocumentCompleteUploadRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[EducationService, Depends(get_education_service)],
) -> EducationDocumentResponse:
    doc = await svc.complete_document_upload(
        current.id, education_id, document_id, payload.checksum_sha256,
    )
    return EducationDocumentResponse.model_validate(doc)


@router.get(
    "/{education_id}/documents/{document_id}/download-url",
    response_model=EducationDocumentDownloadUrlResponse,
)
async def get_education_document_download_url(
    education_id: UUID,
    document_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[EducationService, Depends(get_education_service)],
) -> EducationDocumentDownloadUrlResponse:
    return await svc.get_document_download_url(current.id, education_id, document_id)


@router.delete(
    "/{education_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_education_document(
    education_id: UUID,
    document_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[EducationService, Depends(get_education_service)],
) -> None:
    await svc.delete_document(current.id, education_id, document_id)
