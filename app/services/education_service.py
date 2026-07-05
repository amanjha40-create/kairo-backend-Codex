"""Education and education-document service."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.education.enums import EducationVerificationStatus
from app.exceptions import NotFoundError, ServiceUnavailableError, ValidationAppError
from app.infrastructure.s3.presign import (
    generate_presigned_get_url,
    generate_presigned_put_url,
)
from app.models import Education, EducationDocument
from app.repositories.education import EducationDocumentRepository, EducationRepository
from app.schemas.education import (
    EducationCreateRequest,
    EducationDocumentUploadIntentRequest,
    EducationDocumentUploadIntentResponse,
    EducationDocumentDownloadUrlResponse,
    EducationUpdateRequest,
)

logger = logging.getLogger(__name__)


class EducationService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._educations = EducationRepository(session)
        self._documents = EducationDocumentRepository(session)
        self._settings = settings or get_settings()

    # --- Education CRUD ---

    async def create(self, user_id: UUID, payload: EducationCreateRequest) -> Education:
        edu = Education(
            user_id=user_id,
            institution_name=payload.institution_name,
            degree=payload.degree,
            field_of_study=payload.field_of_study,
            education_level=payload.education_level.value,
            grade=payload.grade,
            start_date=payload.start_date,
            end_date=payload.end_date,
            is_currently_studying=payload.is_currently_studying,
            verification_status=EducationVerificationStatus.DRAFT.value,
        )
        await self._educations.create(edu)
        await self._session.commit()
        await self._session.refresh(edu)
        return edu

    async def list_for_user(
        self, user_id: UUID, *, offset: int = 0, limit: int = 50,
    ):
        return await self._educations.list_for_user(user_id, offset=offset, limit=limit)

    async def get_owned(self, user_id: UUID, education_id: UUID) -> Education:
        edu = await self._educations.get_owned(education_id, user_id)
        if edu is None:
            raise NotFoundError("Education record not found")
        return edu

    async def update(
        self, user_id: UUID, education_id: UUID, payload: EducationUpdateRequest,
    ) -> Education:
        edu = await self.get_owned(user_id, education_id)
        data = payload.model_dump(exclude_unset=True)
        for field, value in data.items():
            if field == "education_level" and value is not None:
                setattr(edu, field, value.value if hasattr(value, "value") else value)
            else:
                setattr(edu, field, value)
        await self._session.commit()
        await self._session.refresh(edu)
        return edu

    async def submit(self, user_id: UUID, education_id: UUID) -> Education:
        edu = await self.get_owned(user_id, education_id)
        if edu.verification_status not in (
            EducationVerificationStatus.DRAFT.value,
            EducationVerificationStatus.REJECTED.value,
        ):
            raise ValidationAppError("Education already submitted")
        edu.verification_status = EducationVerificationStatus.SUBMITTED.value
        edu.submitted_at = datetime.now(tz=UTC)
        await self._session.commit()
        await self._session.refresh(edu)
        return edu

    async def delete(self, user_id: UUID, education_id: UUID) -> None:
        edu = await self.get_owned(user_id, education_id)
        await self._educations.soft_delete(edu)
        await self._session.commit()

    # --- Education documents ---

    async def list_documents(
        self, user_id: UUID, education_id: UUID, *, offset: int = 0, limit: int = 50,
    ):
        await self.get_owned(user_id, education_id)  # ownership check
        return await self._documents.list_for_education(
            education_id, offset=offset, limit=limit,
        )

    async def create_document_upload_intent(
        self,
        user_id: UUID,
        education_id: UUID,
        payload: EducationDocumentUploadIntentRequest,
    ) -> EducationDocumentUploadIntentResponse:
        await self.get_owned(user_id, education_id)  # ownership check

        bucket = self._settings.s3_documents_bucket
        if not bucket:
            raise ServiceUnavailableError("Document storage is not configured")

        document_id = uuid.uuid4()
        prefix = self._settings.s3_document_key_prefix.rstrip("/")
        object_key = f"{prefix}/education-documents/{education_id}/{document_id}/{payload.original_filename}"

        doc = EducationDocument(
            id=document_id,
            education_id=education_id,
            uploaded_by_user_id=user_id,
            document_type=payload.document_type.value,
            object_key=object_key,
            original_filename=payload.original_filename,
            content_type=payload.content_type,
            byte_size=payload.byte_size,
            checksum_sha256="",
            verification_status="pending",
        )
        await self._documents.create(doc)

        upload_url = await generate_presigned_put_url(
            bucket=bucket,
            object_key=object_key,
            content_type=payload.content_type,
            ttl_seconds=self._settings.s3_presigned_put_ttl_seconds,
            settings=self._settings,
        )

        await self._session.commit()

        return EducationDocumentUploadIntentResponse(
            document_id=document_id,
            object_key=object_key,
            bucket=bucket,
            upload_url=upload_url,
            expires_in_seconds=self._settings.s3_presigned_put_ttl_seconds,
            headers_required={"Content-Type": payload.content_type},
        )

    async def complete_document_upload(
        self,
        user_id: UUID,
        education_id: UUID,
        document_id: UUID,
        checksum_sha256: str,
    ) -> EducationDocument:
        await self.get_owned(user_id, education_id)
        doc = await self._documents.get_for_education(document_id, education_id)
        if doc is None:
            raise NotFoundError("Education document not found")
        doc.checksum_sha256 = checksum_sha256
        await self._session.commit()
        await self._session.refresh(doc)
        return doc

    async def get_document_download_url(
        self, user_id: UUID, education_id: UUID, document_id: UUID,
    ) -> EducationDocumentDownloadUrlResponse:
        await self.get_owned(user_id, education_id)
        doc = await self._documents.get_for_education(document_id, education_id)
        if doc is None:
            raise NotFoundError("Education document not found")
        bucket = self._settings.s3_documents_bucket
        if not bucket:
            raise ServiceUnavailableError("Document storage is not configured")
        ttl = 300
        url = await generate_presigned_get_url(
            bucket=bucket, object_key=doc.object_key, ttl_seconds=ttl, settings=self._settings,
        )
        return EducationDocumentDownloadUrlResponse(
            document_id=doc.id, download_url=url, expires_in_seconds=ttl,
        )

    async def delete_document(
        self, user_id: UUID, education_id: UUID, document_id: UUID,
    ) -> None:
        await self.get_owned(user_id, education_id)
        doc = await self._documents.get_for_education(document_id, education_id)
        if doc is None:
            raise NotFoundError("Education document not found")
        await self._documents.soft_delete(doc)
        await self._session.commit()
