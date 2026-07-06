"""Evidence uploads — presigned S3 PUT, direct upload, list, delete."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_employment_document_service
from app.schemas.employment.responses import DocumentDownloadUrlResponse
from app.schemas.employment_document import (
    DocumentCompleteUploadRequest,
    DocumentUploadCompleteResponse,
    DocumentUploadIntentRequest,
    DocumentUploadIntentResponse,
    EmploymentDocumentPublic,
)
from app.schemas.pagination import Page, PageParams
from app.services.employment_document_service import EmploymentDocumentService

router = APIRouter(prefix="/employments", tags=["employment-documents"])


@router.post(
    "/{employment_id}/documents/upload-intent",
    response_model=DocumentUploadIntentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_upload_intent(
    employment_id: UUID,
    payload: DocumentUploadIntentRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[EmploymentDocumentService, Depends(get_employment_document_service)],
) -> DocumentUploadIntentResponse:
    """Mint DB row + short-lived presigned PUT URL — client uploads bytes directly to S3."""

    return await svc.create_upload_intent(current.id, employment_id, payload)


@router.post(
    "/{employment_id}/documents/{document_id}/complete-upload",
    response_model=DocumentUploadCompleteResponse,
)
async def complete_document_upload(
    employment_id: UUID,
    document_id: UUID,
    payload: DocumentCompleteUploadRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[EmploymentDocumentService, Depends(get_employment_document_service)],
) -> DocumentUploadCompleteResponse:
    """Finalize metadata after PUT — validates object size in S3 (no AI extraction)."""

    return await svc.complete_upload(current.id, employment_id, document_id, payload)


@router.delete(
    "/{employment_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_employment_document(
    employment_id: UUID,
    document_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[EmploymentDocumentService, Depends(get_employment_document_service)],
) -> None:
    """Remove an uploaded document while the employment case is still editable."""

    await svc.delete_document_owned(current.id, employment_id, document_id)


@router.get(
    "/{employment_id}/documents/{document_id}/download-url",
    response_model=DocumentDownloadUrlResponse,
)
async def get_document_download_url(
    employment_id: UUID,
    document_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    svc: Annotated[EmploymentDocumentService, Depends(get_employment_document_service)],
) -> DocumentDownloadUrlResponse:
    """Get a short-lived presigned GET URL to view or download an uploaded document."""

    return await svc.get_download_url(current.id, employment_id, document_id)


@router.get("/{employment_id}/documents", response_model=Page[EmploymentDocumentPublic])
async def list_documents(
    employment_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    page: Annotated[PageParams, Depends()],
    svc: Annotated[EmploymentDocumentService, Depends(get_employment_document_service)],
) -> Page[EmploymentDocumentPublic]:
    items, total = await svc.list_for_employment_owned(current.id, employment_id, offset=page.offset, limit=page.limit)
    return Page[EmploymentDocumentPublic].create(items=items, total=total, params=page)
