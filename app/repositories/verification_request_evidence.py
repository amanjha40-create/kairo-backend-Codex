"""Repository for verification request evidence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.verification_request_evidence import VerificationRequestEvidence


class VerificationRequestEvidenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, evidence: VerificationRequestEvidence) -> VerificationRequestEvidence:
        self._session.add(evidence)
        await self._session.flush()
        return evidence

    async def get_by_public_id(self, evidence_public_id: UUID) -> VerificationRequestEvidence | None:
        stmt = select(VerificationRequestEvidence).where(VerificationRequestEvidence.public_id == evidence_public_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_request(self, verification_request_id: UUID) -> list[VerificationRequestEvidence]:
        stmt = (
            select(VerificationRequestEvidence)
            .where(VerificationRequestEvidence.verification_request_id == verification_request_id)
            .order_by(VerificationRequestEvidence.created_at.asc())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())

    async def get_by_employment_document(
        self,
        verification_request_id: UUID,
        employment_document_id: UUID,
    ) -> VerificationRequestEvidence | None:
        stmt = select(VerificationRequestEvidence).where(
            VerificationRequestEvidence.verification_request_id == verification_request_id,
            VerificationRequestEvidence.employment_document_id == employment_document_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_document(
        self,
        verification_request_id: UUID,
        document_id: UUID,
    ) -> VerificationRequestEvidence | None:
        stmt = select(VerificationRequestEvidence).where(
            VerificationRequestEvidence.verification_request_id == verification_request_id,
            VerificationRequestEvidence.document_id == document_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_request_by_field(
        self,
        verification_request_id: UUID,
        field_key: str,
    ) -> list[VerificationRequestEvidence]:
        stmt = (
            select(VerificationRequestEvidence)
            .where(
                VerificationRequestEvidence.verification_request_id == verification_request_id,
                VerificationRequestEvidence.field_key == field_key,
            )
            .order_by(VerificationRequestEvidence.created_at.asc())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())
