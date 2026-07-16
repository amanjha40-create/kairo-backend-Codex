from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.infrastructure.s3.client import get_s3_client
from app.infrastructure.s3.service import S3UploadService
from app.models.resume_document import ResumeDocument
from app.models.resume_parsed_result import ResumeParsedResult
from app.models.resume_processing_job import ResumeProcessingJob
from app.resumes.enums import ResumeProcessingStatus, ResumeUploadStatus
from app.resumes.providers import DeterministicDocxExtractor, TextractDocumentExtractor, build_resume_parser
from app.resumes.validation import validate_resume_bytes, validate_resume_declaration
from app.schemas.pagination import Page, PageParams
from app.resumes.schemas import (
    ResumeCompleteUploadRequest, ResumeParsedResultResponse, ResumeProcessResponse,
    ResumeResponse, ResumeUploadIntentRequest, ResumeUploadIntentResponse,
)
from app.services.job_dispatcher import JobDispatcher

logger = logging.getLogger(__name__)


class ResumeService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.storage = S3UploadService(settings)

    def _enabled(self) -> None:
        if not self.settings.resume_processing_enabled:
            raise ValidationAppError("Resume processing is not enabled")

    async def create_upload_intent(self, user_id: UUID, payload: ResumeUploadIntentRequest) -> ResumeUploadIntentResponse:
        self._enabled()
        safe = validate_resume_declaration(
            filename=payload.original_filename, content_type=payload.content_type,
            byte_size=payload.byte_size, max_bytes=self.settings.resume_max_upload_bytes,
        )
        resume_id = uuid.uuid4()
        key = f"resumes/{user_id}/{resume_id}/{safe}"
        row = ResumeDocument(
            id=resume_id, user_id=user_id, storage_bucket=self.settings.s3_documents_bucket or "",
            storage_key=key, original_filename=payload.original_filename, normalized_filename=safe,
            content_type=payload.content_type.split(";", 1)[0].lower(), file_size_bytes=payload.byte_size,
            upload_status=ResumeUploadStatus.PENDING_UPLOAD.value, processing_status=ResumeUploadStatus.PENDING_UPLOAD.value,
            consent_at=datetime.now(UTC), consent_version=payload.consent_version,
            expires_at=datetime.now(UTC) + timedelta(days=self.settings.resume_retention_days),
        )
        self.session.add(row)
        await self.session.flush()
        url, ttl = await self.storage.presign_put_url(object_key=key, content_type=row.content_type)
        await self.session.commit()
        return ResumeUploadIntentResponse(resume_id=resume_id, upload_url=url, expires_in=ttl, object_key=key)

    async def _owned(self, user_id: UUID, resume_id: UUID) -> ResumeDocument:
        row = await self.session.scalar(select(ResumeDocument).where(
            ResumeDocument.id == resume_id, ResumeDocument.user_id == user_id, ResumeDocument.deleted_at.is_(None),
        ))
        if row is None:
            raise NotFoundError("Resume not found")
        return row

    async def complete_upload(self, user_id: UUID, resume_id: UUID, payload: ResumeCompleteUploadRequest) -> ResumeResponse:
        row = await self._owned(user_id, resume_id)
        if row.upload_status == ResumeUploadStatus.UPLOADED.value:
            return ResumeResponse.model_validate(row)
        await self.storage.verify_upload_matches_intent(
            object_key=row.storage_key, expected_byte_size=row.file_size_bytes, declared_content_type=row.content_type,
        )
        data = await self._read_object(row)
        validate_resume_bytes(data, content_type=row.content_type, max_bytes=self.settings.resume_max_upload_bytes)
        if hashlib.sha256(data).hexdigest().lower() != payload.checksum_sha256.lower():
            raise ValidationAppError("Uploaded resume checksum does not match")
        row.checksum_sha256 = payload.checksum_sha256.lower()
        row.upload_status = ResumeUploadStatus.UPLOADED.value
        row.processing_status = ResumeUploadStatus.UPLOADED.value
        await self.session.commit()
        await self.session.refresh(row)
        return ResumeResponse.model_validate(row)

    async def _read_object(self, row: ResumeDocument) -> bytes:
        def read() -> bytes:
            client = get_s3_client(self.settings)
            return client.get_object(Bucket=row.storage_bucket, Key=row.storage_key)["Body"].read(self.settings.resume_max_upload_bytes + 1)
        return await asyncio.to_thread(read)

    async def process(self, user_id: UUID, resume_id: UUID) -> ResumeProcessResponse:
        row = await self._owned(user_id, resume_id)
        if row.upload_status != ResumeUploadStatus.UPLOADED.value:
            raise ConflictError("Resume must be uploaded before processing")
        existing = await self.session.scalar(select(ResumeProcessingJob).where(
            ResumeProcessingJob.resume_document_id == resume_id,
            ResumeProcessingJob.status.in_([ResumeProcessingStatus.QUEUED.value, ResumeProcessingStatus.EXTRACTING.value, ResumeProcessingStatus.PARSING.value]),
        ))
        if existing:
            return ResumeProcessResponse(resume_id=resume_id, job_id=existing.id, status=existing.status)
        job = ResumeProcessingJob(resume_document_id=resume_id, user_id=user_id, idempotency_key=str(uuid.uuid4()), parser_schema_version=self.settings.resume_parser_schema_version)
        self.session.add(job)
        row.processing_status = ResumeProcessingStatus.QUEUED.value
        # The inline worker uses a separate session and must see the durable job.
        await self.session.commit()
        await JobDispatcher(self.settings).dispatch_resume_processing(resume_id=str(resume_id), job_id=str(job.id))
        return ResumeProcessResponse(resume_id=resume_id, job_id=job.id, status=job.status)

    async def list(self, user_id: UUID, offset: int, limit: int) -> Page[ResumeResponse]:
        rows = list((await self.session.scalars(select(ResumeDocument).where(ResumeDocument.user_id == user_id, ResumeDocument.deleted_at.is_(None)).order_by(ResumeDocument.created_at.desc()).offset(offset).limit(limit))).all())
        total = await self.session.scalar(select(func.count()).select_from(ResumeDocument).where(ResumeDocument.user_id == user_id, ResumeDocument.deleted_at.is_(None))) or 0
        return Page[ResumeResponse].create(
            items=[ResumeResponse.model_validate(r) for r in rows],
            total=total,
            params=PageParams(offset=offset, limit=limit),
        )

    async def get(self, user_id: UUID, resume_id: UUID) -> ResumeResponse:
        return ResumeResponse.model_validate(await self._owned(user_id, resume_id))

    async def status(self, user_id: UUID, resume_id: UUID) -> ResumeProcessResponse:
        row = await self._owned(user_id, resume_id)
        job = await self.session.scalar(select(ResumeProcessingJob).where(ResumeProcessingJob.resume_document_id == resume_id).order_by(ResumeProcessingJob.created_at.desc()))
        if not job:
            raise NotFoundError("Resume processing job not found")
        return ResumeProcessResponse(resume_id=row.id, job_id=job.id, status=job.status)

    async def parsed_result(self, user_id: UUID, resume_id: UUID) -> ResumeParsedResultResponse:
        row = await self._owned(user_id, resume_id)
        result = await self.session.scalar(select(ResumeParsedResult).join(ResumeProcessingJob).where(ResumeProcessingJob.resume_document_id == row.id))
        if result is None:
            raise NotFoundError("Parsed resume result is not available")
        job = await self.session.get(ResumeProcessingJob, result.job_id)
        return ResumeParsedResultResponse(resume_id=row.id, job_id=result.job_id, schema_version=result.schema_version, status=job.status, structured_result=result.structured_result, warnings=result.warnings)

    async def delete(self, user_id: UUID, resume_id: UUID) -> None:
        row = await self._owned(user_id, resume_id)
        row.deleted_at = datetime.now(UTC)
        row.upload_status = ResumeUploadStatus.DELETED.value
        row.processing_status = ResumeProcessingStatus.DELETED.value
        await self.storage.delete_object_best_effort(object_key=row.storage_key)
        await self.session.commit()

    async def process_job(self, resume_id: UUID, job_id: UUID) -> None:
        row = await self.session.get(ResumeDocument, resume_id)
        job = await self.session.get(ResumeProcessingJob, job_id)
        if row is None or job is None or row.deleted_at is not None or row.processing_status == ResumeProcessingStatus.DELETED.value:
            return
        job.attempt_count += 1
        job.status = ResumeProcessingStatus.EXTRACTING.value
        row.processing_status = job.status
        await self.session.flush()
        try:
            content = await self._read_object(row)
            if row.content_type == "application/pdf":
                extracted = await TextractDocumentExtractor(self.settings).extract(content, row.content_type)
            else:
                extracted = await DeterministicDocxExtractor().extract(content, row.content_type)
            job.status = ResumeProcessingStatus.PARSING.value
            row.processing_status = job.status
            await self.session.flush()
            parsed = await build_resume_parser(self.settings).parse(extracted)
            result = ResumeParsedResult(
                job_id=job.id, user_id=row.user_id, schema_version=parsed.schema_version,
                structured_result=parsed.model_dump(mode="json"), parser_metadata={"provider": "bedrock"}, warnings=parsed.warnings,
            )
            self.session.add(result)
            job.status = ResumeProcessingStatus.NEEDS_REVIEW.value
            row.processing_status = job.status
            job.completed_at = datetime.now(UTC)
            await self.session.flush()
        except Exception as exc:
            job.status = ResumeProcessingStatus.FAILED.value
            row.processing_status = job.status
            job.failure_category = type(exc).__name__[:64]
            job.sanitized_failure_code = "processing_failed"
            row.failure_code = "processing_failed"
            logger.warning("resume.processing.failed", extra={"resume_id": str(resume_id), "job_id": str(job_id), "error_type": type(exc).__name__})
            await self.session.flush()
