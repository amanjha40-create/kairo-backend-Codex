"""Employment evidence documents — delegates uploads to `DocumentUploadService`."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.employment.document_catalog import build_document_upload_options
from app.exceptions import EmploymentAccessDeniedError, EmploymentCaseNotFoundError, NotFoundError
from app.repositories.employment import EmploymentRepository
from app.repositories.employment_document import EmploymentDocumentRepository
from app.infrastructure.s3.presign import generate_presigned_get_url
from app.schemas.employment.responses import DocumentDownloadUrlResponse, DocumentUploadOptionsResponse
from app.schemas.employment_document import (
    DocumentCompleteUploadRequest,
    DocumentUploadCompleteResponse,
    DocumentUploadIntentRequest,
    DocumentUploadIntentResponse,
    EmploymentDocumentPublic,
)
from app.services.document_upload_service import DocumentUploadService


class EmploymentDocumentService:
    """Coordinates listing/metadata and composes `DocumentUploadService` for S3 flows."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._uploads = DocumentUploadService(session, settings)
        self._settings = settings
        self._employment = EmploymentRepository(session)
        self._documents = EmploymentDocumentRepository(session)

    def get_upload_options(self) -> DocumentUploadOptionsResponse:
        return DocumentUploadOptionsResponse.model_validate(build_document_upload_options(self._settings))

    async def create_upload_intent(
        self,
        owner_user_id: UUID,
        employment_id: UUID,
        payload: DocumentUploadIntentRequest,
    ) -> DocumentUploadIntentResponse:
        return await self._uploads.create_upload_intent(owner_user_id, employment_id, payload)

    async def complete_upload(
        self,
        owner_user_id: UUID,
        employment_id: UUID,
        document_id: UUID,
        payload: DocumentCompleteUploadRequest,
    ) -> DocumentUploadCompleteResponse:
        return await self._uploads.complete_upload(owner_user_id, employment_id, document_id, payload)

    async def delete_document_owned(
        self,
        owner_user_id: UUID,
        employment_id: UUID,
        document_id: UUID,
    ) -> None:
        await self._uploads.delete_document(owner_user_id, employment_id, document_id)

    async def get_document_owned(
        self,
        owner_user_id: UUID,
        document_id: UUID,
    ) -> EmploymentDocumentPublic:
        doc = await self._documents.get_active_by_id(document_id)
        if doc is None:
            raise NotFoundError("Document not found")
        emp = await self._employment.get_owned_active(doc.employment_id, owner_user_id)
        if emp is None:
            raise EmploymentAccessDeniedError()
        return EmploymentDocumentPublic.model_validate(doc)

    async def get_download_url(
        self,
        owner_user_id: UUID,
        employment_id: UUID,
        document_id: UUID,
        ttl_seconds: int = 300,
    ) -> DocumentDownloadUrlResponse:
        emp = await self._employment.get_owned_active(employment_id, owner_user_id)
        if emp is None:
            raise EmploymentCaseNotFoundError()
        doc = await self._documents.get_active_by_id(document_id)
        if doc is None or doc.employment_id != employment_id:
            raise NotFoundError("Document not found")

        bucket = self._settings.s3_documents_bucket
        if not bucket:
            raise NotFoundError("Document storage is not configured")

        url = await generate_presigned_get_url(
            bucket=bucket,
            object_key=doc.object_key,
            ttl_seconds=ttl_seconds,
            settings=self._settings,
        )
        return DocumentDownloadUrlResponse(
            document_id=document_id,
            download_url=url,
            expires_in_seconds=ttl_seconds,
        )

    async def list_for_employment_owned(
        self,
        owner_user_id: UUID,
        employment_id: UUID,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[EmploymentDocumentPublic], int]:
        emp = await self._employment.get_owned_active(employment_id, owner_user_id)
        if emp is None:
            raise EmploymentCaseNotFoundError()

        rows, total = await self._documents.list_for_employment(
            employment_id,
            offset=offset,
            limit=limit,
        )
        return [EmploymentDocumentPublic.model_validate(r) for r in rows], total
