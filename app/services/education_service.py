"""Education and education-document service."""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalogues.education_identity import education_identity
from app.config import Settings, get_settings
from app.education.enums import EducationVerificationStatus
from app.exceptions import NotFoundError, ServiceUnavailableError, ValidationAppError
from app.infrastructure.s3.presign import (
    generate_presigned_get_url,
    generate_presigned_put_url,
)
from app.models import Education, EducationDocument
from app.repositories.education import EducationDocumentRepository, EducationRepository
from app.repositories.verification_request import VerificationRequestRepository
from app.resumes.normalization import date_ranges_overlap, normalize_text
from app.schemas.education import (
    EducationCreateRequest,
    EducationDocumentDownloadUrlResponse,
    EducationDocumentUploadIntentRequest,
    EducationDocumentUploadIntentResponse,
    EducationEvidencePreviewResponse,
    EducationEvidenceResponse,
    EducationEvidenceStructuredPreview,
    EducationResponse,
    EducationUpdateRequest,
)
from app.services.digilocker_verification_projection import education_verification_projections
from app.services.document_pack_storage import DocumentPackStorage
from app.verification_requests.enums import VerificationRequestStatus

logger = logging.getLogger(__name__)

_EVIDENCE_LABELS = {
    "degree_certificate": "Degree certificate",
    "passing_certificate": "Passing certificate",
    "provisional_certificate": "Provisional certificate",
    "transcript": "Transcript",
    "marksheet": "Marksheet",
    "migration_certificate": "Migration certificate",
    "admission_letter": "Admission letter",
    "enrollment_proof": "Enrollment proof",
    "other": "Education document",
}


def _digilocker_metadata(document: EducationDocument) -> dict | None:
    payload = document.extracted_payload
    metadata = payload.get("digilocker") if isinstance(payload, dict) else None
    if isinstance(metadata, dict) and metadata.get("source") == "digilocker":
        return metadata
    return None


def _preview_type(document: EducationDocument) -> str | None:
    mime = document.content_type.split(";", 1)[0].lower()
    if mime == "application/pdf":
        return "pdf"
    if mime in {"image/jpeg", "image/png", "image/webp"}:
        return "image"
    if mime in {"application/xml", "text/xml"} and _digilocker_metadata(document):
        return "structured"
    return None


class EducationService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._educations = EducationRepository(session)
        self._documents = EducationDocumentRepository(session)
        self._verification_requests = VerificationRequestRepository(session)
        self._settings = settings or get_settings()

    # --- Education CRUD ---

    async def create(self, user_id: UUID, payload: EducationCreateRequest) -> Education:
        identity = education_identity(payload.model_dump())
        await self._assert_not_obvious_duplicate(
            user_id=user_id,
            institution_name=payload.institution_name,
            degree=payload.degree,
            field_of_study=payload.field_of_study,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )
        edu = Education(
            user_id=user_id,
            institution_name=payload.institution_name,
            degree=payload.degree,
            field_of_study=payload.field_of_study,
            education_level=payload.education_level.value,
            institution_catalogue_id=identity.get("institution_catalogue_id"),
            institution_catalogue_version=identity.get("institution_catalogue_version"),
            grade=payload.grade,
            start_date=payload.start_date,
            start_date_precision=payload.start_date_precision,
            end_date=payload.end_date,
            end_date_precision=payload.end_date_precision,
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

    async def responses(self, educations: list[Education]) -> list[EducationResponse]:
        projections = await education_verification_projections(self._session, educations)
        education_ids = [education.id for education in educations]
        evidence_by_education: dict[UUID, list[EducationEvidenceResponse]] = defaultdict(list)
        if education_ids:
            documents = list(
                (
                    await self._session.scalars(
                        select(EducationDocument).where(
                            EducationDocument.education_id.in_(education_ids),
                            EducationDocument.deleted_at.is_(None),
                        )
                    )
                ).all()
            )
            for document in documents:
                metadata = _digilocker_metadata(document)
                preview_type = _preview_type(document)
                if metadata is None or preview_type is None:
                    continue
                evidence_by_education[document.education_id].append(
                    EducationEvidenceResponse(
                        evidence_id=document.id,
                        document_type=document.document_type,
                        display_name=_EVIDENCE_LABELS.get(
                            document.document_type, "Education document"
                        ),
                        source="digilocker",
                        verification_status=document.verification_status,
                        verified_at=document.verified_at,
                        preview_available=True,
                        preview_type=preview_type,
                        content_type=(
                            document.content_type if preview_type in {"pdf", "image"} else None
                        ),
                    )
                )
        return [
            EducationResponse.model_validate(education).model_copy(
                update={
                    "verification_status": projections[education.id].status,
                    "verification_source": projections[education.id].source,
                    "verified_at": projections[education.id].verified_at,
                    "evidence": evidence_by_education[education.id],
                }
            )
            for education in educations
        ]

    async def response(self, education: Education) -> EducationResponse:
        return (await self.responses([education]))[0]

    async def update(
        self, user_id: UUID, education_id: UUID, payload: EducationUpdateRequest,
    ) -> Education:
        edu = await self.get_owned(user_id, education_id)
        previous_status = edu.verification_status
        latest_request = None
        if previous_status != EducationVerificationStatus.REJECTED.value:
            latest_request = await self._verification_requests.get_latest_for_subject_education(
                education_id=education_id,
                subject_user_id=user_id,
            )
        recovering_rejection = (
            previous_status == EducationVerificationStatus.REJECTED.value
            or (
                latest_request is not None
                and latest_request.status == VerificationRequestStatus.REJECTED
            )
        )
        data = education_identity(payload.model_dump(exclude_unset=True), edu)
        start_date = data.get("start_date", edu.start_date)
        end_date = data.get("end_date", edu.end_date)
        is_currently_studying = data.get("is_currently_studying", edu.is_currently_studying)
        if end_date and start_date and end_date < start_date:
            raise ValidationAppError(
                "End date must be on or after start date",
                code="invalid_education_date_range",
            )
        if is_currently_studying and end_date is not None:
            raise ValidationAppError(
                "End date must be blank while currently studying",
                code="invalid_education_current_status",
            )
        await self._assert_not_obvious_duplicate(
            user_id=user_id,
            institution_name=data.get("institution_name", edu.institution_name),
            degree=data.get("degree", edu.degree),
            field_of_study=data.get("field_of_study", edu.field_of_study),
            start_date=start_date,
            end_date=end_date,
            exclude_education_id=edu.id,
        )
        for field, value in data.items():
            if field == "education_level" and value is not None:
                setattr(edu, field, value.value if hasattr(value, "value") else value)
            else:
                setattr(edu, field, value)
        if recovering_rejection:
            edu.verification_status = EducationVerificationStatus.DRAFT.value
            edu.submitted_at = None
            edu.reviewed_at = None
            edu.verified_at = None
            edu.reviewed_by_user_id = None
            edu.reviewer_note = None
        await self._session.commit()
        await self._session.refresh(edu)
        return edu

    async def _assert_not_obvious_duplicate(
        self,
        *,
        user_id: UUID,
        institution_name: str | None,
        degree: str | None,
        field_of_study: str | None,
        start_date: object,
        end_date: object,
        exclude_education_id: UUID | None = None,
    ) -> None:
        """Reject only records that are indistinguishable from an existing study period."""
        if not institution_name or not (degree or field_of_study) or not start_date:
            return
        rows, _ = await self._educations.list_for_user(user_id, offset=0, limit=200)
        institution = normalize_text(institution_name)
        programme = normalize_text(degree or field_of_study)
        for existing in rows:
            if existing.id == exclude_education_id:
                continue
            existing_programme = normalize_text(existing.degree or existing.field_of_study)
            if (
                normalize_text(existing.institution_name) == institution
                and existing_programme == programme
                and date_ranges_overlap(
                    start_date,
                    end_date,
                    existing.start_date,
                    existing.end_date,
                )
            ):
                raise ValidationAppError(
                    "This education record appears to duplicate an existing study period",
                    code="duplicate_education_record",
                )

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
        object_key = (
            f"{prefix}/education-documents/{education_id}/{document_id}/"
            f"{payload.original_filename}"
        )

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
        from app.services.evidence_review import invalidate_document_reviews, lock_review_subject

        await lock_review_subject(self._session, user_id)
        await self.get_owned(user_id, education_id)
        doc = await self._documents.get_for_education(document_id, education_id)
        if doc is None:
            raise NotFoundError("Education document not found")
        await self._session.refresh(doc)
        if doc.checksum_sha256 != checksum_sha256:
            await invalidate_document_reviews(
                self._session,
                "education_document_id",
                doc.id,
                user_id,
            )
        doc.checksum_sha256 = checksum_sha256
        await self._session.commit()
        await self._session.refresh(doc)
        return doc

    async def document_content(self, user_id: UUID, education_id: UUID, document_id: UUID):
        from app.services.private_document_content import private_document_content

        await self.get_owned(user_id, education_id)
        doc = await self._documents.get_for_education(document_id, education_id)
        if doc is None:
            raise NotFoundError("Education document not found")
        return await private_document_content(
            self._settings, doc,
            completed=bool(doc.checksum_sha256 and doc.checksum_sha256 != "0" * 64),
        )

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

    async def get_evidence_preview(
        self, user_id: UUID, education_id: UUID, evidence_id: UUID,
    ) -> EducationEvidencePreviewResponse:
        education = await self.get_owned(user_id, education_id)
        document = await self._documents.get_for_education(evidence_id, education_id)
        if document is None or _digilocker_metadata(document) is None:
            raise NotFoundError("Education evidence not found")
        preview_type = _preview_type(document)
        if preview_type is None:
            raise NotFoundError("Education evidence preview is unavailable")

        if preview_type in {"pdf", "image"}:
            binding = await DocumentPackStorage(self._settings).inspect(document.object_key)
            if binding.size != document.byte_size or binding.content_type != document.content_type:
                raise NotFoundError("Education evidence preview is unavailable")
            ttl = 300
            url = await generate_presigned_get_url(
                bucket=self._settings.s3_documents_bucket,
                object_key=document.object_key,
                ttl_seconds=ttl,
                settings=self._settings,
            )
            return EducationEvidencePreviewResponse(
                evidence_id=document.id,
                preview_type=preview_type,
                content_type=document.content_type,
                preview_url=url,
                expires_in_seconds=ttl,
            )

        metadata = _digilocker_metadata(document) or {}
        safe_preview = metadata.get("safe_preview")
        safe_preview = safe_preview if isinstance(safe_preview, dict) else {}
        year = safe_preview.get("completion_year")
        if not isinstance(year, int):
            year = education.end_date.year if education.end_date else None
        qualification = safe_preview.get("qualification")
        if not isinstance(qualification, str) or not qualification.strip():
            qualification = education.degree
        issuer = metadata.get("issuer_name")
        if not isinstance(issuer, str) or not issuer.strip():
            issuer = None
        return EducationEvidencePreviewResponse(
            evidence_id=document.id,
            preview_type="structured",
            structured=EducationEvidenceStructuredPreview(
                document_type=document.document_type,
                issuer=issuer,
                qualification=qualification,
                completion_year=year,
                verification_source="digilocker",
                verified_at=document.verified_at,
            ),
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
