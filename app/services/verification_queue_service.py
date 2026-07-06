"""Review queues, verification timelines, AI preparation, and queue fan-out payloads."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.employment.constants import (
    TIMELINE_META_AI_PIPELINE_KIND,
    VERIFICATION_REVIEW_TRIAGE_JOB_TYPE,
)
from app.employment.enums import DocumentExtractionStatus, VerificationAuditAction, VerificationStatus
from app.employment.verification.confidence import ConfidenceScore
from app.employment.verification.timeline import VerificationTimelineEvent, from_audit_row
from app.exceptions import EmploymentCaseNotFoundError
from app.repositories.admin import AdminRepository
from app.repositories.employment import EmploymentRepository
from app.repositories.employment_document import EmploymentDocumentRepository
from app.repositories.verification import VerificationRepository
from app.schemas.employment import EmploymentPublic
from app.schemas.pagination import Page, PageParams

logger = logging.getLogger(__name__)

_TERMINAL_EXTRACTION: frozenset[str] = frozenset(
    {
        DocumentExtractionStatus.COMPLETED.value,
        DocumentExtractionStatus.FAILED.value,
        DocumentExtractionStatus.SKIPPED.value,
    }
)


@dataclass(frozen=True, slots=True)
class AiPipelinePreparationResult:
    """Outcome of AI / rules preparation — includes confidence placeholder for `extraction_preview`."""

    employment_id: UUID
    total_documents: int
    documents_terminal_extraction: int
    ready_for_rules_engine: bool
    confidence_preview: dict[str, Any] | None


class VerificationQueueService:
    """Queue-oriented verification orchestration — async session scoped, audit-backed."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._admin = AdminRepository(session)
        self._verification = VerificationRepository(session)
        self._employment = EmploymentRepository(session)
        self._documents = EmploymentDocumentRepository(session)

    async def list_review_queue(
        self,
        *,
        offset: int,
        limit: int,
        statuses: list[str] | None,
        employer_ilike: str | None,
        created_after: date | None,
        created_before: date | None,
    ) -> Page[EmploymentPublic]:
        """Operational reviewer listing — thin delegate over indexed repository filters."""

        rows, total = await self._admin.list_employment_queue(
            offset=offset,
            limit=limit,
            statuses=statuses,
            employer_ilike=employer_ilike,
            created_after=created_after,
            created_before=created_before,
        )
        return Page[EmploymentPublic].create(
            items=[EmploymentPublic.model_validate(r) for r in rows],
            total=total,
            params=PageParams(offset=offset, limit=limit),
        )

    async def list_pending_verifications(
        self,
        *,
        offset: int,
        limit: int,
        statuses: list[str] | None = None,
        employer_ilike: str | None = None,
        submitted_after: date | None = None,
        submitted_before: date | None = None,
    ) -> Page[EmploymentPublic]:
        """Submitted / under_review slice — prioritises reviewer throughput ordering."""

        rows, total = await self._verification.get_pending_verifications(
            offset=offset,
            limit=limit,
            statuses=statuses,
            employer_ilike=employer_ilike,
            submitted_after=submitted_after,
            submitted_before=submitted_before,
        )
        return Page[EmploymentPublic].create(
            items=[EmploymentPublic.model_validate(r) for r in rows],
            total=total,
            params=PageParams(offset=offset, limit=limit),
        )

    async def get_timeline_for_viewer(
        self,
        employment_id: UUID,
        *,
        offset: int,
        limit: int,
        viewer_user_id: UUID,
        is_admin: bool,
    ) -> Page[VerificationTimelineEvent]:
        """Immutable audit stream projected as timeline events — ownership enforced for applicants."""

        if not is_admin:
            row = await self._employment.get_owned_active(employment_id, viewer_user_id)
            if row is None:
                raise EmploymentCaseNotFoundError()

        rows, total = await self._verification.list_for_employment(
            employment_id,
            offset=offset,
            limit=limit,
        )
        items = [from_audit_row(r) for r in rows]
        return Page[VerificationTimelineEvent].create(
            items=items,
            total=total,
            params=PageParams(offset=offset, limit=limit),
        )

    async def prepare_ai_extraction_pipeline(
        self,
        employment_id: UUID,
        *,
        viewer_user_id: UUID | None,
        is_admin: bool = False,
        seed_preview: bool = True,
        record_audit: bool = True,
    ) -> AiPipelinePreparationResult:
        """Gate automated checks on terminal extraction; seed confidence JSON + optional audit row."""

        if is_admin:
            row = await self._employment.get_active_by_id(employment_id)
        else:
            if viewer_user_id is None:
                raise EmploymentCaseNotFoundError()
            row = await self._employment.get_owned_active(employment_id, viewer_user_id)
        if row is None:
            raise EmploymentCaseNotFoundError()

        docs, _ = await self._documents.list_for_employment(employment_id, offset=0, limit=500)
        terminal = sum(1 for d in docs if d.extraction_status in _TERMINAL_EXTRACTION)
        ready = len(docs) > 0 and terminal == len(docs)

        confidence = ConfidenceScore()
        confidence_fragment = confidence.to_preview_fragment()

        if seed_preview and ready:
            prev = row.extraction_preview or {}
            row.extraction_preview = {
                **prev,
                "schema_version": max(int(prev.get("schema_version", 0) or 0), 2),
                "confidence": confidence_fragment,
                "pipeline": {
                    "ai_ready": True,
                    "documents_total": len(docs),
                    "documents_terminal_extraction": terminal,
                },
            }
            await self._employment.update(row)

            if record_audit:
                await self._verification.append(
                    employment_id=employment_id,
                    actor_user_id=viewer_user_id,
                    action=VerificationAuditAction.REVIEWER_NOTE_RECORDED.value,
                    previous_status=None,
                    new_status=None,
                    metadata_payload={
                        "kind": TIMELINE_META_AI_PIPELINE_KIND,
                        "confidence": confidence_fragment,
                        "pipeline_ready": ready,
                    },
                )
            await self._session.commit()
            logger.info(
                "verification.ai_pipeline.prepared",
                extra={"employment_id": str(employment_id), "seeded": True},
            )
        else:
            logger.debug(
                "verification.ai_pipeline.skipped_seed",
                extra={
                    "employment_id": str(employment_id),
                    "ready": ready,
                    "documents": len(docs),
                },
            )

        return AiPipelinePreparationResult(
            employment_id=employment_id,
            total_documents=len(docs),
            documents_terminal_extraction=terminal,
            ready_for_rules_engine=ready,
            confidence_preview=confidence_fragment if ready else None,
        )

    def build_review_triage_job_envelope(self, *, employment_id: UUID, priority: str = "normal") -> dict[str, Any]:
        """Serializable payload for async review workers — pair with `VERIFICATION_REVIEW_TRIAGE_JOB_TYPE`."""

        return {
            "employment_id": str(employment_id),
            "priority": priority,
            "target_status_hint": VerificationStatus.UNDER_REVIEW.value,
        }

    @staticmethod
    def review_triage_job_type() -> str:
        return VERIFICATION_REVIEW_TRIAGE_JOB_TYPE
