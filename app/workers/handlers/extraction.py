"""SQS handlers for document extraction pipeline — workers run outside the API process."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.employment.constants import DOCUMENT_EXTRACTION_JOB_TYPE
from app.employment.enums import DocumentExtractionStatus, VerificationAuditAction
from app.repositories.employment_document import EmploymentDocumentRepository
from app.repositories.verification_audit import VerificationAuditRepository
from app.workers.registry import register_handler


@register_handler(DOCUMENT_EXTRACTION_JOB_TYPE)
async def extract_employment_document(data: dict[str, Any], session: AsyncSession) -> None:
    """Prepare structured payload slot — replace stub with ML inference + OCR orchestration."""

    doc_id = UUID(str(data["document_id"]))
    docs = EmploymentDocumentRepository(session)
    audit = VerificationAuditRepository(session)

    doc = await docs.get_active_by_id(doc_id)
    if doc is None:
        return

    if doc.extraction_status != DocumentExtractionStatus.QUEUED.value:
        return

    now = datetime.now(tz=UTC)
    doc.extraction_status = DocumentExtractionStatus.PROCESSING.value
    doc.extraction_started_at = now
    doc.extraction_attempt_count += 1
    await session.flush()

    await audit.append(
        employment_id=doc.employment_id,
        actor_user_id=None,
        action=VerificationAuditAction.EXTRACTION_STARTED.value,
        previous_status=None,
        new_status=None,
        metadata_payload={"document_id": str(doc.id), "attempt": doc.extraction_attempt_count},
    )

    # --- Integration seam: stream from S3, call model endpoint, validate JSON schema. ---
    doc.extracted_payload = {
        "pipeline_version": "2026.05.stub",
        "normalized": {},
        "confidence": None,
        "notes": "Replace with production OCR + LLM extraction output.",
    }
    doc.extraction_status = DocumentExtractionStatus.COMPLETED.value
    doc.extraction_completed_at = datetime.now(tz=UTC)
    doc.extraction_last_error = None

    await audit.append(
        employment_id=doc.employment_id,
        actor_user_id=None,
        action=VerificationAuditAction.EXTRACTION_COMPLETED.value,
        previous_status=None,
        new_status=None,
        metadata_payload={"document_id": str(doc.id)},
    )
