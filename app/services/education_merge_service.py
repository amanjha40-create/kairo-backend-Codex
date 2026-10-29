"""Guarded canonical merge for proven duplicate Education records."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.education.entity_resolution import resolve_education_entity
from app.exceptions import ConflictError, NotFoundError
from app.models import Education, EducationDocument, VerificationRequest

logger = logging.getLogger(__name__)


def _fingerprint(document: EducationDocument) -> str | None:
    payload = document.extracted_payload
    metadata = payload.get("digilocker") if isinstance(payload, dict) else None
    value = metadata.get("reference_fingerprint") if isinstance(metadata, dict) else None
    return value if isinstance(value, str) and len(value) == 64 else None


@dataclass(frozen=True, slots=True)
class EducationMergeResult:
    canonical_id: UUID
    retired_id: UUID
    evidence_moved: int
    verification_requests_moved: int
    match_result: str


class EducationMergeService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def merge_digilocker_duplicate(
        self, *, user_id: UUID, canonical_id: UUID, duplicate_id: UUID,
    ) -> EducationMergeResult:
        if canonical_id == duplicate_id:
            raise ConflictError("Education merge requires two different records")
        rows = list(
            (
                await self._session.scalars(
                    select(Education)
                    .where(
                        Education.id.in_([canonical_id, duplicate_id]),
                        Education.user_id == user_id,
                        Education.deleted_at.is_(None),
                    )
                    .with_for_update()
                )
            ).all()
        )
        by_id = {row.id: row for row in rows}
        canonical = by_id.get(canonical_id)
        duplicate = by_id.get(duplicate_id)
        if canonical is None or duplicate is None:
            raise NotFoundError("Education merge records not found")

        resolution = resolve_education_entity(
            institution_name=duplicate.institution_name,
            qualification=duplicate.degree or duplicate.field_of_study,
            education_level=duplicate.education_level,
            completion_year_value=duplicate.end_date.year if duplicate.end_date else None,
            educations=[canonical],
        )
        if resolution.state != "CLEAR_MATCH":
            raise ConflictError("Education records are not a deterministic match")

        documents = list(
            (
                await self._session.scalars(
                    select(EducationDocument)
                    .where(
                        EducationDocument.education_id.in_([canonical_id, duplicate_id]),
                        EducationDocument.deleted_at.is_(None),
                    )
                    .with_for_update()
                )
            ).all()
        )
        source_documents = [row for row in documents if row.education_id == duplicate_id]
        if not source_documents:
            raise ConflictError("Duplicate Education has no evidence to merge")
        if not any(_fingerprint(row) for row in source_documents):
            raise ConflictError("Duplicate Education is not linked to DigiLocker evidence")
        target_fingerprints = {
            value
            for row in documents
            if row.education_id == canonical_id
            if (value := _fingerprint(row)) is not None
        }
        if any(_fingerprint(row) in target_fingerprints for row in source_documents):
            raise ConflictError("Canonical Education already has this DigiLocker evidence")

        requests = list(
            (
                await self._session.scalars(
                    select(VerificationRequest)
                    .where(VerificationRequest.education_id == duplicate_id)
                    .with_for_update()
                )
            ).all()
        )
        for document in source_documents:
            document.education_id = canonical_id
        for request in requests:
            request.education_id = canonical_id

        accepted = [row.verified_at for row in source_documents if row.verified_at is not None]
        if accepted:
            canonical.verification_status = "verified"
            verified_at = min(accepted)
            if canonical.verified_at is None or verified_at < canonical.verified_at:
                canonical.verified_at = verified_at
        duplicate.deleted_at = datetime.now(tz=UTC)
        await self._session.commit()
        logger.info(
            "digilocker_education_duplicate_merged",
            extra={
                "canonical_education_id": str(canonical_id),
                "retired_education_id": str(duplicate_id),
                "evidence_moved": len(source_documents),
                "verification_requests_moved": len(requests),
            },
        )
        return EducationMergeResult(
            canonical_id=canonical_id,
            retired_id=duplicate_id,
            evidence_moved=len(source_documents),
            verification_requests_moved=len(requests),
            match_result=resolution.state,
        )
