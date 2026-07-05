"""Flat document routes — catalog, presigned URL, confirm upload, fetch, delete."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_employment_document_service
from app.config import Settings, get_settings
from app.employment.document_catalog import build_document_upload_options
from app.schemas.employment.requests import DocumentConfirmUploadRequest, DocumentPresignedUrlRequest
from app.schemas.employment_document import (
    DocumentCompleteUploadRequest,
    DocumentUploadCompleteResponse,
    DocumentUploadIntentRequest,
    DocumentUploadIntentResponse,
    DocumentUploadOptionsResponse,
    EmploymentDocumentPublic,
)
from app.services.employment_document_service import EmploymentDocumentService

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/upload-options", response_model=DocumentUploadOptionsResponse, summary="Allowed document types and MIME types")
async def get_document_upload_options(
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentUploadOptionsResponse:
    """Frontend catalog — document categories, file types, and size limits (no auth required)."""

    return DocumentUploadOptionsResponse.model_validate(build_document_upload_options(settings))


@router.post(
    "/presigned-url",
    response_model=DocumentUploadIntentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_presigned_upload_url(
    payload: DocumentPresignedUrlRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[EmploymentDocumentService, Depends(get_employment_document_service)],
) -> DocumentUploadIntentResponse:
    inner = DocumentUploadIntentRequest.model_validate(
        payload.model_dump(exclude={"employment_id"}),
    )
    return await svc.create_upload_intent(current.id, payload.employment_id, inner)


@router.post("/confirm-upload", response_model=DocumentUploadCompleteResponse)
async def confirm_document_upload(
    payload: DocumentConfirmUploadRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[EmploymentDocumentService, Depends(get_employment_document_service)],
) -> DocumentUploadCompleteResponse:
    body = DocumentCompleteUploadRequest.model_validate(
        payload.model_dump(exclude={"employment_id", "document_id"}),
    )
    return await svc.complete_upload(
        current.id,
        payload.employment_id,
        payload.document_id,
        body,
    )


@router.get("/{document_id}", response_model=EmploymentDocumentPublic)
async def get_document(
    document_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[EmploymentDocumentService, Depends(get_employment_document_service)],
) -> EmploymentDocumentPublic:
    return await svc.get_document_owned(current.id, document_id)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    employment_id: Annotated[UUID, Query(description="Employment case that owns the document")],
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[EmploymentDocumentService, Depends(get_employment_document_service)],
) -> None:
    """Soft-delete evidence — only while the employment case is editable (draft / additional info)."""

    await svc.delete_document_owned(current.id, employment_id, document_id)
