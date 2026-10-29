"""Authoritative DigiLocker verification projections for canonical records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Education, EducationDocument


@dataclass(frozen=True)
class EducationVerificationProjection:
    status: str
    source: str | None
    verified_at: datetime | None


def _is_verified_digilocker_evidence(document: EducationDocument) -> bool:
    payload = document.extracted_payload
    metadata = payload.get("digilocker") if isinstance(payload, dict) else None
    return bool(
        document.deleted_at is None
        and document.verification_status == "verified"
        and document.verified_at is not None
        and isinstance(metadata, dict)
        and metadata.get("source") == "digilocker"
    )


async def education_verification_projections(
    session: AsyncSession,
    educations: list[Education],
) -> dict[UUID, EducationVerificationProjection]:
    """Project canonical state from accepted evidence without changing persisted rows."""
    education_ids = [education.id for education in educations]
    if not education_ids:
        return {}
    documents = list(
        (
            await session.execute(
                select(EducationDocument).where(
                    EducationDocument.education_id.in_(education_ids),
                    EducationDocument.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    )
    accepted_at: dict[UUID, datetime] = {}
    for document in documents:
        if not _is_verified_digilocker_evidence(document):
            continue
        current = accepted_at.get(document.education_id)
        if current is None or document.verified_at < current:
            accepted_at[document.education_id] = document.verified_at

    projections = {}
    for education in educations:
        digilocker_verified_at = accepted_at.get(education.id)
        if digilocker_verified_at is not None:
            projections[education.id] = EducationVerificationProjection(
                status="verified",
                source="digilocker",
                verified_at=digilocker_verified_at,
            )
        else:
            projections[education.id] = EducationVerificationProjection(
                status=education.verification_status,
                source=None,
                verified_at=education.verified_at,
            )
    return projections
