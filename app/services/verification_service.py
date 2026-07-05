"""Verification workflow orchestration — submission readiness, AI hand-off, queue triggers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.employment.enums import VerificationStatus
from app.exceptions import EmploymentCaseNotFoundError
from app.repositories.employment import EmploymentRepository
from app.repositories.employment_document import EmploymentDocumentRepository
from app.schemas.employment import EmploymentSubmitResponse
from app.services.employment_service import EmploymentService
from app.services.verification_queue_service import VerificationQueueService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SubmissionReadiness:
    """Non-mutating assessment prior to submit."""

    employment_id: UUID
    active_documents: int
    can_submit_status: bool
    pipeline_clear_for_owner: bool


@dataclass(frozen=True, slots=True)
class AiVerificationPreparation:
    """Structured hand-off for downstream AI / rules engines."""

    employment_id: UUID
    total_documents: int
    documents_terminal_extraction: int
    ready_for_rules_engine: bool
    confidence_preview: dict[str, Any] | None = None


class VerificationService:
    """Coordinates verification pipeline steps without replacing applicant/admin endpoints."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._employment = EmploymentRepository(session)
        self._documents = EmploymentDocumentRepository(session)
        self._employment_service = EmploymentService(session)
        self._queues = VerificationQueueService(session)

    async def prepare_queue_submission_readiness(
        self,
        owner_user_id: UUID,
        employment_id: UUID,
    ) -> SubmissionReadiness:
        """Validate ownership, documents, and concurrent pipeline constraints — does not mutate."""

        row = await self._employment.get_owned_active(employment_id, owner_user_id)
        if row is None:
            raise EmploymentCaseNotFoundError()

        doc_count = await self._documents.count_active_for_employment(employment_id)
        can_submit = row.verification_status in (
            VerificationStatus.DRAFT.value,
            VerificationStatus.ADDITIONAL_INFO_REQUESTED.value,
        )
        conflicts = await self._employment.count_owner_pipeline_excluding(
            owner_user_id,
            exclude_employment_id=employment_id,
            pipeline_statuses=(
                VerificationStatus.SUBMITTED.value,
                VerificationStatus.UNDER_REVIEW.value,
            ),
        )
        pipeline_clear = conflicts == 0

        logger.debug(
            "verification.submission_readiness",
            extra={
                "employment_id": str(employment_id),
                "owner_user_id": str(owner_user_id),
                "documents": doc_count,
                "pipeline_clear": pipeline_clear,
            },
        )

        return SubmissionReadiness(
            employment_id=employment_id,
            active_documents=doc_count,
            can_submit_status=can_submit,
            pipeline_clear_for_owner=pipeline_clear,
        )

    async def trigger_verification_submission(
        self,
        owner_user_id: UUID,
        employment_id: UUID,
    ) -> EmploymentSubmitResponse:
        """Delegates to `EmploymentService.submit` — authoritative validation and audit."""

        return await self._employment_service.submit(owner_user_id, employment_id)

    async def prepare_ai_verification(
        self,
        owner_user_id: UUID,
        employment_id: UUID,
        *,
        seed_preview_stub: bool = False,
    ) -> AiVerificationPreparation:
        """Ensure evidence has stable extraction outcomes before automated checks."""

        result = await self._queues.prepare_ai_extraction_pipeline(
            employment_id,
            viewer_user_id=owner_user_id,
            is_admin=False,
            seed_preview=seed_preview_stub,
            record_audit=seed_preview_stub,
        )

        logger.debug(
            "verification.ai_preparation",
            extra={
                "employment_id": str(employment_id),
                "documents": result.total_documents,
                "terminal_extraction": result.documents_terminal_extraction,
                "ready": result.ready_for_rules_engine,
            },
        )

        return AiVerificationPreparation(
            employment_id=result.employment_id,
            total_documents=result.total_documents,
            documents_terminal_extraction=result.documents_terminal_extraction,
            ready_for_rules_engine=result.ready_for_rules_engine,
            confidence_preview=result.confidence_preview,
        )
