"""Production S3-backed employment document upload orchestration."""

from __future__ import annotations

import logging
import uuid
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.employment.constants import PENDING_UPLOAD_CHECKSUM_HEX
from app.employment.enums import (
    DocumentExtractionStatus,
    DocumentVerificationStatus,
    VerificationAuditAction,
    VerificationMethod,
    VerificationStatus,
)
from app.exceptions import (
    DuplicateEmploymentDocumentError,
    EmploymentCaseNotFoundError,
    EmploymentWorkflowError,
    NotFoundError,
)
from app.infrastructure.s3.paths import build_user_employment_document_key, sanitize_filename_for_storage
from app.infrastructure.s3.service import S3UploadService
from app.models.employment_document import EmploymentDocument
from app.repositories.employment import EmploymentRepository
from app.repositories.employment_document import EmploymentDocumentRepository
from app.repositories.verification_audit import VerificationAuditRepository
from app.schemas.employment.responses import (
    DocumentUploadCompleteResponse,
    DocumentUploadIntentResponse,
)
from app.schemas.employment_document import (
    DocumentCompleteUploadRequest,
    DocumentUploadIntentRequest,
)

logger = logging.getLogger(__name__)


class DocumentUploadService:
    """Presigned URL issuance and S3 confirmation — direct upload, no extraction queue."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._storage = S3UploadService(settings)
        self._employment = EmploymentRepository(session)
        self._documents = EmploymentDocumentRepository(session)
        self._audit = VerificationAuditRepository(session)

    async def create_upload_intent(
        self,
        owner_user_id: UUID,
        employment_id: UUID,
        payload: DocumentUploadIntentRequest,
    ) -> DocumentUploadIntentResponse:
        self._storage.validate_declaration(byte_size=payload.byte_size, content_type=payload.content_type)

        emp = await self._employment.get_owned_active(employment_id, owner_user_id)
        if emp is None:
            raise EmploymentCaseNotFoundError()
        if emp.verification_method == VerificationMethod.EMPLOYER_CONFIRMATION.value:
            raise EmploymentWorkflowError(
                "Document upload is not used for employer confirmation verification",
            )
        if emp.verification_status not in (
            VerificationStatus.DRAFT.value,
            VerificationStatus.SUBMITTED.value,
            VerificationStatus.ADDITIONAL_INFO_REQUESTED.value,
        ):
            raise EmploymentWorkflowError("Documents cannot be attached in the current workflow state")

        safe_name = sanitize_filename_for_storage(payload.original_filename)
        dup_intent = await self._documents.count_pending_intent_duplicate(
            employment_id,
            document_type=payload.document_type.value,
            original_filename=safe_name,
            pending_checksum_hex=PENDING_UPLOAD_CHECKSUM_HEX,
        )
        if dup_intent > 0:
            logger.warning(
                "document.upload_intent.duplicate",
                extra={
                    "employment_id": str(employment_id),
                    "document_type": payload.document_type.value,
                },
            )
            raise DuplicateEmploymentDocumentError(
                "An upload for this document type and filename is already in progress",
            )

        doc_id = uuid.uuid4()
        object_key = build_user_employment_document_key(
            owner_user_id=owner_user_id,
            employment_id=employment_id,
            document_id=doc_id,
            safe_filename=safe_name,
            prefix=self._settings.s3_document_key_prefix,
        )

        row = EmploymentDocument(
            id=doc_id,
            employment_id=employment_id,
            uploaded_by_user_id=owner_user_id,
            document_type=payload.document_type.value,
            object_key=object_key,
            original_filename=safe_name,
            content_type=payload.content_type,
            byte_size=payload.byte_size,
            checksum_sha256=PENDING_UPLOAD_CHECKSUM_HEX,
            verification_status=DocumentVerificationStatus.PENDING_UPLOAD.value,
            extraction_status=DocumentExtractionStatus.SKIPPED.value,
        )
        row = await self._documents.create(row)

        upload_url, ttl = await self._storage.presign_put_url(
            object_key=object_key,
            content_type=payload.content_type,
        )

        bucket = self._settings.s3_documents_bucket
        assert bucket is not None  # implied after successful presign

        await self._audit.append(
            employment_id=employment_id,
            actor_user_id=owner_user_id,
            action=VerificationAuditAction.DOCUMENT_REGISTERED.value,
            previous_status=None,
            new_status=None,
            metadata_payload={
                "document_id": str(doc_id),
                "document_type": payload.document_type.value,
                "byte_size": payload.byte_size,
            },
        )
        await self._session.commit()

        logger.info(
            "document.upload_intent.created",
            extra={
                "employment_id": str(employment_id),
                "document_id": str(doc_id),
                "owner_user_id": str(owner_user_id),
            },
        )

        return DocumentUploadIntentResponse(
            document_id=doc_id,
            object_key=object_key,
            bucket=bucket,
            upload_url=upload_url,
            expires_in_seconds=ttl,
            headers_required={"Content-Type": payload.content_type},
        )

    async def complete_upload(
        self,
        owner_user_id: UUID,
        employment_id: UUID,
        document_id: UUID,
        payload: DocumentCompleteUploadRequest,
    ) -> DocumentUploadCompleteResponse:
        doc = await self._documents.get_active_by_id(document_id)
        if doc is None:
            raise NotFoundError("Document not found")

        if doc.employment_id != employment_id:
            raise EmploymentWorkflowError("Document does not belong to this employment case")

        emp = await self._employment.get_owned_active(doc.employment_id, owner_user_id)
        if emp is None:
            raise EmploymentCaseNotFoundError()

        if doc.checksum_sha256 != PENDING_UPLOAD_CHECKSUM_HEX:
            raise EmploymentWorkflowError("Upload already finalized")

        dup_digest = await self._documents.count_other_active_with_checksum(
            employment_id,
            payload.checksum_sha256,
            exclude_document_id=document_id,
        )
        if dup_digest > 0:
            logger.warning(
                "document.complete.duplicate_checksum",
                extra={"employment_id": str(employment_id), "document_id": str(document_id)},
            )
            raise DuplicateEmploymentDocumentError(
                "Another document with the same content already exists for this case",
            )

        await self._storage.verify_upload_matches_intent(
            object_key=doc.object_key,
            expected_byte_size=doc.byte_size,
            declared_content_type=doc.content_type,
        )

        doc.checksum_sha256 = payload.checksum_sha256
        doc.extraction_status = DocumentExtractionStatus.SKIPPED.value
        doc.verification_status = DocumentVerificationStatus.PENDING_REVIEW.value
        doc.verified_at = None
        doc.verified_by_user_id = None
        doc.reviewer_note = None

        await self._audit.append(
            employment_id=doc.employment_id,
            actor_user_id=owner_user_id,
            action=VerificationAuditAction.DOCUMENT_UPLOAD_COMPLETED.value,
            previous_status=None,
            new_status=None,
            metadata_payload={"document_id": str(doc.id), "checksum_sha256": payload.checksum_sha256},
        )

        await self._session.commit()
        logger.info(
            "document.upload.completed",
            extra={
                "employment_id": str(employment_id),
                "document_id": str(document_id),
            },
        )
        return DocumentUploadCompleteResponse(document_id=doc.id, message="Upload complete")

    async def delete_document(
        self,
        owner_user_id: UUID,
        employment_id: UUID,
        document_id: UUID,
    ) -> None:
        doc = await self._documents.get_active_by_id(document_id)
        if doc is None:
            raise NotFoundError("Document not found")
        if doc.employment_id != employment_id:
            raise EmploymentWorkflowError("Document does not belong to this employment case")

        emp = await self._employment.get_owned_active(employment_id, owner_user_id)
        if emp is None:
            raise EmploymentCaseNotFoundError()
        if emp.verification_status not in (
            VerificationStatus.DRAFT.value,
            VerificationStatus.SUBMITTED.value,
            VerificationStatus.ADDITIONAL_INFO_REQUESTED.value,
        ):
            raise EmploymentWorkflowError("Documents cannot be removed in the current workflow state")

        if doc.checksum_sha256 != PENDING_UPLOAD_CHECKSUM_HEX:
            await self._storage.delete_object_best_effort(object_key=doc.object_key)

        await self._documents.soft_delete(document_id)
        await self._session.commit()
        logger.info(
            "document.deleted",
            extra={
                "employment_id": str(employment_id),
                "document_id": str(document_id),
                "owner_user_id": str(owner_user_id),
            },
        )
