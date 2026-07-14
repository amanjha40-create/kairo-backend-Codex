"""Repositories for verification request admin review data."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.admin_review.enums import VerificationReviewCorrectionStatus
from app.models.verification_request_review import VerificationRequestReview
from app.models.verification_review_correction import VerificationReviewCorrection
from app.models.verification_review_note import VerificationReviewNote


class VerificationRequestReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_review(self, review: VerificationRequestReview) -> VerificationRequestReview:
        self._session.add(review)
        await self._session.flush()
        return review

    async def get_review_by_public_id(self, review_public_id: UUID) -> VerificationRequestReview | None:
        stmt = select(VerificationRequestReview).where(VerificationRequestReview.public_id == review_public_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_reviews_for_request(self, verification_request_id: UUID) -> list[VerificationRequestReview]:
        stmt = (
            select(VerificationRequestReview)
            .where(VerificationRequestReview.verification_request_id == verification_request_id)
            .order_by(VerificationRequestReview.review_round.asc(), VerificationRequestReview.created_at.asc())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())

    async def get_latest_review_for_request(self, verification_request_id: UUID) -> VerificationRequestReview | None:
        stmt = (
            select(VerificationRequestReview)
            .where(VerificationRequestReview.verification_request_id == verification_request_id)
            .order_by(VerificationRequestReview.review_round.desc(), VerificationRequestReview.created_at.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_next_review_round(self, verification_request_id: UUID) -> int:
        stmt = select(func.max(VerificationRequestReview.review_round)).where(
            VerificationRequestReview.verification_request_id == verification_request_id
        )
        current = (await self._session.execute(stmt)).scalar_one_or_none()
        return int(current or 0) + 1

    async def create_note(self, note: VerificationReviewNote) -> VerificationReviewNote:
        self._session.add(note)
        await self._session.flush()
        return note

    async def list_notes_for_review(self, verification_request_review_id: UUID) -> list[VerificationReviewNote]:
        stmt = (
            select(VerificationReviewNote)
            .where(VerificationReviewNote.verification_request_review_id == verification_request_review_id)
            .order_by(VerificationReviewNote.created_at.asc())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())

    async def list_notes_for_request(self, verification_request_review_ids: list[UUID]) -> list[VerificationReviewNote]:
        if not verification_request_review_ids:
            return []
        stmt = (
            select(VerificationReviewNote)
            .where(VerificationReviewNote.verification_request_review_id.in_(verification_request_review_ids))
            .order_by(VerificationReviewNote.created_at.asc())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())

    async def create_correction(self, correction: VerificationReviewCorrection) -> VerificationReviewCorrection:
        self._session.add(correction)
        await self._session.flush()
        return correction

    async def list_corrections_for_review(
        self,
        verification_request_review_id: UUID,
    ) -> list[VerificationReviewCorrection]:
        stmt = (
            select(VerificationReviewCorrection)
            .options(joinedload(VerificationReviewCorrection.evidence_item))
            .where(VerificationReviewCorrection.verification_request_review_id == verification_request_review_id)
            .order_by(VerificationReviewCorrection.created_at.asc())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())

    async def list_open_corrections_for_request(
        self,
        verification_request_review_ids: list[UUID],
    ) -> list[VerificationReviewCorrection]:
        if not verification_request_review_ids:
            return []
        stmt = (
            select(VerificationReviewCorrection)
            .options(joinedload(VerificationReviewCorrection.evidence_item))
            .where(
                VerificationReviewCorrection.verification_request_review_id.in_(verification_request_review_ids),
                VerificationReviewCorrection.status == VerificationReviewCorrectionStatus.OPEN,
            )
            .order_by(VerificationReviewCorrection.created_at.asc())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())
