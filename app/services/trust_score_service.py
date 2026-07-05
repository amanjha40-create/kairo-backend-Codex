"""Trust score calculation service — measures profile completeness and verification status."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Education, Employment, User, UserDocument
from app.schemas.trust_score import TrustScoreComponentBreakdown, TrustScoreResponse

logger = logging.getLogger(__name__)


class TrustScoreService:
    """Calculate user trust score across multiple verification dimensions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def calculate_trust_score(self, user_id: UUID) -> TrustScoreResponse:
        """Calculate complete trust score for a user with component breakdown."""
        user = await self._get_user(user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")

        identity_score = await self._calculate_identity_score(user)
        employment_score = await self._calculate_employment_score(user_id)
        education_score = await self._calculate_education_score(user_id)
        documents_score = await self._calculate_documents_score(user_id)

        breakdown = TrustScoreComponentBreakdown(
            identity=identity_score,
            employment=employment_score,
            education=education_score,
            documents=documents_score,
        )

        overall = self._calculate_weighted_overall(breakdown)
        week_change = 0

        return TrustScoreResponse(
            overall=overall,
            breakdown=breakdown,
            week_change=week_change,
        )

    async def _get_user(self, user_id: UUID) -> User | None:
        """Fetch user by ID."""
        stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def _calculate_identity_score(self, user: User) -> int:
        """Calculate identity verification score (0-100).

        Weights:
        - Email verified: 50 points
        - Full name provided: 25 points
        - Profile slug set: 25 points
        """
        score = 0

        if user.email_verified_at is not None:
            score += 50

        if user.full_name and len(user.full_name.strip()) > 0:
            score += 25

        if user.profile_slug and len(user.profile_slug.strip()) > 0:
            score += 25

        return min(score, 100)

    async def _calculate_employment_score(self, user_id: UUID) -> int:
        """Calculate employment verification score (0-100).

        Based on ratio of verified/approved employments to total employments.
        """
        stmt = (
            select(func.count())
            .select_from(Employment)
            .where(Employment.created_by_user_id == user_id, Employment.deleted_at.is_(None))
        )
        total = int((await self._session.execute(stmt)).scalar_one() or 0)

        if total == 0:
            return 0

        stmt_verified = (
            select(func.count())
            .select_from(Employment)
            .where(
                Employment.created_by_user_id == user_id,
                Employment.verification_status == "approved",
                Employment.deleted_at.is_(None),
            )
        )
        verified = int((await self._session.execute(stmt_verified)).scalar_one() or 0)

        return int((verified / total) * 100) if total > 0 else 0

    async def _calculate_education_score(self, user_id: UUID) -> int:
        """Calculate education verification score (0-100).

        Based on ratio of verified education credentials to total credentials.
        """
        stmt = (
            select(func.count())
            .select_from(Education)
            .where(Education.user_id == user_id, Education.deleted_at.is_(None))
        )
        total = int((await self._session.execute(stmt)).scalar_one() or 0)

        if total == 0:
            return 0

        stmt_verified = (
            select(func.count())
            .select_from(Education)
            .where(
                Education.user_id == user_id,
                Education.verification_status == "verified",
                Education.deleted_at.is_(None),
            )
        )
        verified = int((await self._session.execute(stmt_verified)).scalar_one() or 0)

        return int((verified / total) * 100) if total > 0 else 0

    async def _calculate_documents_score(self, user_id: UUID) -> int:
        """Calculate document verification score (0-100).

        Based on ratio of verified documents to total documents.
        """
        stmt = (
            select(func.count())
            .select_from(UserDocument)
            .where(UserDocument.user_id == user_id, UserDocument.deleted_at.is_(None))
        )
        total = int((await self._session.execute(stmt)).scalar_one() or 0)

        if total == 0:
            return 0

        stmt_verified = (
            select(func.count())
            .select_from(UserDocument)
            .where(
                UserDocument.user_id == user_id,
                UserDocument.verification_status == "verified",
                UserDocument.deleted_at.is_(None),
            )
        )
        verified = int((await self._session.execute(stmt_verified)).scalar_one() or 0)

        return int((verified / total) * 100) if total > 0 else 0

    @staticmethod
    def _calculate_weighted_overall(breakdown: TrustScoreComponentBreakdown) -> int:
        """Calculate weighted overall score.

        Weights:
        - Identity: 30%
        - Employment: 25%
        - Education: 20%
        - Documents: 25%
        """
        weighted = (
            breakdown.identity * 0.30
            + breakdown.employment * 0.25
            + breakdown.education * 0.20
            + breakdown.documents * 0.25
        )
        return int(weighted)
