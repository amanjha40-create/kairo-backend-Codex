"""User-level identity documents (Aadhaar, PAN, license, etc.)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_user_document_service
from app.schemas.pagination import Page, PageParams
from app.schemas.user_document import (
    UserDocumentCompleteUploadRequest,
    UserDocumentDownloadUrlResponse,
    UserDocumentResponse,
    UserDocumentUpdateRequest,
    UserDocumentUploadIntentRequest,
    UserDocumentUploadIntentResponse,
)
from app.services.user_document_service import UserDocumentService

router = APIRouter(prefix="/user-documents", tags=["user-documents"])


@router.get("", response_model=Page[UserDocumentResponse])
async def list_my_user_documents(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    page: Annotated[PageParams, Depends()],
    svc: Annotated[UserDocumentService, Depends(get_user_document_service)],
) -> Page[UserDocumentResponse]:
    items, total = await svc.list_for_user(current.id, offset=page.offset, limit=page.limit)
    return Page[UserDocumentResponse].create(
        items=[UserDocumentResponse.model_validate(d) for d in items],
        total=total,
        params=page,
    )


@router.post(
    "/upload-intent",
    response_model=UserDocumentUploadIntentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_upload_intent(
    payload: UserDocumentUploadIntentRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[UserDocumentService, Depends(get_user_document_service)],
) -> UserDocumentUploadIntentResponse:
    """Get a presigned S3 PUT URL; client uploads file directly to S3."""

    return await svc.create_upload_intent(current.id, payload)


@router.post("/{document_id}/complete-upload", response_model=UserDocumentResponse)
async def complete_upload(
    document_id: UUID,
    payload: UserDocumentCompleteUploadRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[UserDocumentService, Depends(get_user_document_service)],
) -> UserDocumentResponse:
    doc = await svc.complete_upload(current.id, document_id, payload.checksum_sha256)
    return UserDocumentResponse.model_validate(doc)


@router.get("/{document_id}", response_model=UserDocumentResponse)
async def get_user_document(
    document_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[UserDocumentService, Depends(get_user_document_service)],
) -> UserDocumentResponse:
    doc = await svc.get_for_user(current.id, document_id)
    return UserDocumentResponse.model_validate(doc)


@router.get("/{document_id}/download-url", response_model=UserDocumentDownloadUrlResponse)
async def get_download_url(
    document_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[UserDocumentService, Depends(get_user_document_service)],
) -> UserDocumentDownloadUrlResponse:
    return await svc.get_download_url(current.id, document_id)


@router.patch("/{document_id}", response_model=UserDocumentResponse)
async def update_user_document(
    document_id: UUID,
    payload: UserDocumentUpdateRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[UserDocumentService, Depends(get_user_document_service)],
) -> UserDocumentResponse:
    doc = await svc.update(current.id, document_id, payload)
    return UserDocumentResponse.model_validate(doc)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_document(
    document_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[UserDocumentService, Depends(get_user_document_service)],
) -> None:
    await svc.delete(current.id, document_id)
