"""Canonical Version 1 Trust Score engine.

The engine consumes existing verification outcomes. It does not verify claims,
change verification state, or infer trust from profile completeness.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import Education, Employment, TrustScoreSnapshot, User, UserDocument
from app.schemas.trust_score import (
    TrustScoreComponentBreakdown,
    TrustScoreConsentRequest,
    TrustScoreContributor,
    TrustScoreDomainScore,
    TrustScoreResponse,
)

_VERIFIED_STATES = {"approved", "verified"}


class TrustScoreService:
    """Calculate and persist explainable, versioned Version 1 scores."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()

    async def record_consent(self, user_id: UUID, payload: TrustScoreConsentRequest) -> None:
        user = await self._get_user(user_id)
        if user is None:
            raise ValueError("User not found")
        user.trust_score_consent_at = datetime.now(UTC)
        user.trust_score_consent_version = payload.consent_version
        await self._session.commit()

    async def withdraw_consent(self, user_id: UUID) -> None:
        user = await self._get_user(user_id)
        if user is None:
            raise ValueError("User not found")
        user.trust_score_consent_at = None
        user.trust_score_consent_version = None
        await self._session.commit()

    async def calculate_trust_score(self, user_id: UUID) -> TrustScoreResponse:
        user = await self._get_user(user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found")

        now = datetime.now(UTC)
        if self._settings.trust_score_require_consent and user.trust_score_consent_at is None:
            response = self._response(
                status="consent_required",
                overall=None,
                breakdown=None,
                domain_details={},
                score_version=self._settings.trust_score_version,
                last_calculated_at=now,
                manual_review_reason="Explicit Trust Score consent is required before screening starts.",
            )
            await self._persist(user, response)
            return response

        identity = await self._identity_domain(user)
        employment = await self._employment_domain(user_id)
        education = await self._education_domain(user_id)
        domains = {"identity": identity, "employment": employment, "education": education}
        positives = [item for domain in domains.values() for item in domain.positive_contributors]
        negatives = [item for domain in domains.values() for item in domain.negative_contributors]
        critical: list[TrustScoreContributor] = []
        weighted = (
            identity.score * self._settings.trust_score_identity_weight
            + employment.score * self._settings.trust_score_employment_weight
            + education.score * self._settings.trust_score_education_weight
        )
        completeness = await self._verification_completeness(user, user_id)
        status = "calculated" if completeness == 100 else "incomplete_verification"
        overall = round(weighted)
        response = self._response(
            status=status,
            overall=overall,
            breakdown=TrustScoreComponentBreakdown(
                identity=round(identity.score, 2), employment=round(employment.score, 2), education=round(education.score, 2)
            ),
            domain_details=domains,
            positive_contributors=positives,
            negative_contributors=negatives,
            critical_overrides=critical,
            manual_review_reason=("Mandatory verification checks remain incomplete." if status != "calculated" else None),
            score_version=self._settings.trust_score_version,
            last_calculated_at=now,
            verification_completeness_percentage=completeness,
        )
        await self._persist(user, response)
        return response

    async def _get_user(self, user_id: UUID) -> User | None:
        return (await self._session.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))).scalar_one_or_none()

    async def _identity_domain(self, user: User) -> TrustScoreDomainScore:
        documents = list((await self._session.execute(
            select(UserDocument).where(UserDocument.user_id == user.id, UserDocument.deleted_at.is_(None))
        )).scalars().all())
        identity_doc = next((doc for doc in documents if doc.verification_status in _VERIFIED_STATES), None)
        self_attested_doc = next((doc for doc in documents if doc.verification_status not in {"rejected", "cancelled"}), None)
        points = 0.0
        positives: list[TrustScoreContributor] = []
        if identity_doc:
            points += 40
            positives.append(TrustScoreContributor(code="identity_authoritative", label="Identity document verified", points=40, detail="Approved identity evidence provides the authoritative tier."))
        elif self_attested_doc:
            points += 10
            positives.append(TrustScoreContributor(code="identity_self_attested", label="Identity document submitted", points=10, detail="Candidate-submitted identity evidence is self-attested only."))
        if user.phone_verified_at:
            points += 15
            positives.append(TrustScoreContributor(code="phone_verified", label="Mobile number verified", points=15, detail="Phone OTP verification is complete."))
        if user.email_verified_at:
            points += 15
            positives.append(TrustScoreContributor(code="email_verified", label="Email verified", points=15, detail="Email verification is complete."))
        return self._domain(points, 70, self._settings.trust_score_identity_weight, positives, [])

    async def _employment_domain(self, user_id: UUID) -> TrustScoreDomainScore:
        rows = list((await self._session.execute(
            select(Employment).where(Employment.created_by_user_id == user_id, Employment.deleted_at.is_(None))
        )).scalars().all())
        if not rows:
            return self._domain(0, 100, self._settings.trust_score_employment_weight, [], [TrustScoreContributor(code="employment_missing", label="Employment verification missing", points=0, detail="No employment claim is available for verification.")])
        total = 0.0
        positives: list[TrustScoreContributor] = []
        for row in rows:
            if row.verification_status in _VERIFIED_STATES:
                total += 30 + 30 + 20
                positives.append(TrustScoreContributor(code="employment_authoritative", label=f"Employment verified: {row.employer_legal_name}", points=80, detail="The existing employment workflow marked the claim approved."))
            elif row.verification_status not in {"rejected", "cancelled"}:
                total += 7.5
                positives.append(TrustScoreContributor(code="employment_self_attested", label=f"Employment submitted: {row.employer_legal_name}", points=7.5, detail="The claim is submitted but not third-party or authoritative verified."))
        score = total / len(rows)
        negatives = [] if total else [TrustScoreContributor(code="employment_unverified", label="Employment not verified", points=0, detail="No verification outcome supports the employment claim.")]
        return self._domain(score, 100, self._settings.trust_score_employment_weight, positives, negatives)

    async def _education_domain(self, user_id: UUID) -> TrustScoreDomainScore:
        rows = list((await self._session.execute(
            select(Education).where(Education.user_id == user_id, Education.deleted_at.is_(None))
        )).scalars().all())
        if not rows:
            return self._domain(0, 100, self._settings.trust_score_education_weight, [], [TrustScoreContributor(code="education_missing", label="Education verification missing", points=0, detail="No education claim is available for verification.")])
        total = 0.0
        positives: list[TrustScoreContributor] = []
        for row in rows:
            if row.verification_status in _VERIFIED_STATES:
                total += 70
                positives.append(TrustScoreContributor(code="education_authoritative", label=f"Education verified: {row.institution_name}", points=70, detail="The existing education workflow marked the credential verified."))
            elif row.verification_status not in {"rejected", "cancelled"}:
                total += 17.5
                positives.append(TrustScoreContributor(code="education_self_attested", label=f"Education submitted: {row.institution_name}", points=17.5, detail="The credential is candidate-submitted and not independently verified."))
        return self._domain(total / len(rows), 100, self._settings.trust_score_education_weight, positives, [])

    async def _verification_completeness(self, user: User, user_id: UUID) -> int:
        employments = list((await self._session.execute(select(Employment).where(Employment.created_by_user_id == user_id, Employment.deleted_at.is_(None)))).scalars().all())
        educations = list((await self._session.execute(select(Education).where(Education.user_id == user_id, Education.deleted_at.is_(None)))).scalars().all())
        checks = [bool(user.email_verified_at), bool(user.phone_verified_at), bool(user.trust_score_consent_at)]
        checks.extend(row.verification_status in _VERIFIED_STATES for row in employments)
        checks.extend(row.verification_status in _VERIFIED_STATES for row in educations)
        return round(sum(checks) * 100 / len(checks)) if checks else 0

    @staticmethod
    def _domain(points: float, maximum: float, weight: float, positives: list[TrustScoreContributor], negatives: list[TrustScoreContributor]) -> TrustScoreDomainScore:
        return TrustScoreDomainScore(score=max(0, min(100, points / maximum * 100)), verification_points=max(0, points), fraud_deduction=0, weight=weight, positive_contributors=positives, negative_contributors=negatives)

    @staticmethod
    def _response(**kwargs) -> TrustScoreResponse:  # noqa: ANN003
        return TrustScoreResponse(**kwargs)

    async def _persist(self, user: User, response: TrustScoreResponse) -> None:
        latest = (await self._session.execute(
            select(TrustScoreSnapshot)
            .where(TrustScoreSnapshot.user_id == user.id)
            .order_by(desc(TrustScoreSnapshot.calculated_at))
            .limit(1)
        )).scalar_one_or_none()
        if latest is not None and self._snapshot_matches(latest, response, user):
            response.last_calculated_at = latest.calculated_at
            return
        self._session.add(TrustScoreSnapshot(
            user_id=user.id,
            score_version=response.score_version,
            status=response.status,
            overall_score=response.overall,
            verification_completeness_percentage=response.verification_completeness_percentage,
            domain_scores={key: value.model_dump() for key, value in response.domain_details.items()},
            positive_contributors=[item.model_dump() for item in response.positive_contributors],
            negative_contributors=[item.model_dump() for item in response.negative_contributors],
            critical_overrides=[item.model_dump() for item in response.critical_overrides],
            manual_review_reason=response.manual_review_reason,
            consent_at=user.trust_score_consent_at,
            calculated_at=response.last_calculated_at or datetime.now(UTC),
        ))
        await self._session.commit()

    @staticmethod
    def _snapshot_matches(snapshot: TrustScoreSnapshot, response: TrustScoreResponse, user: User) -> bool:
        return (
            snapshot.score_version == response.score_version
            and snapshot.status == response.status
            and snapshot.overall_score == response.overall
            and snapshot.verification_completeness_percentage == response.verification_completeness_percentage
            and snapshot.domain_scores == {key: value.model_dump() for key, value in response.domain_details.items()}
            and snapshot.positive_contributors == [item.model_dump() for item in response.positive_contributors]
            and snapshot.negative_contributors == [item.model_dump() for item in response.negative_contributors]
            and snapshot.critical_overrides == [item.model_dump() for item in response.critical_overrides]
            and snapshot.manual_review_reason == response.manual_review_reason
            and snapshot.consent_at == user.trust_score_consent_at
        )
