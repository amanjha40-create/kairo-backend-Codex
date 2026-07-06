"""Backend-owned Trust Passport aggregation services."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Certification, Education, Employment, GigPlatform, Internship, PortfolioItem, User, UserDocument
from app.models.freelance_contract import FreelanceContract
from app.models.passport_share_link import PassportShareLink
from app.models.passport_share_view import PassportShareView
from app.schemas.passport_engine import (
    OwnerPassportResponse,
    PassportMetadata,
    PassportSectionStatusSummary,
    PassportSharingSummary,
    PassportVerificationSummary,
)
from app.schemas.passport_share import PassportSharePermissions
from app.services.public_passport_service import PublicPassportService
from app.services.trust_score_service import TrustScoreService
from app.services.user_service import UserService


class PassportEngineService:
    """Canonical owner-facing Trust Passport aggregation."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._users = UserService(session, settings)
        self._trust = TrustScoreService(session)
        self._public_passport = PublicPassportService(session, settings)

    async def get_owner_passport(self, user_id: UUID) -> OwnerPassportResponse:
        profile = await self._users.get_public_profile(user_id)
        trust_score = await self._trust.calculate_trust_score(user_id)
        vault = await self._public_passport.build_vault_for_user(
            user_id,
            PassportSharePermissions(
                include_employments=True,
                include_educations=True,
                include_internships=True,
                include_freelance=True,
                include_gig_platforms=True,
                include_portfolio=True,
                include_certifications=True,
                include_user_documents=True,
                show_employer_names=True,
                show_documents=True,
                show_trust_score=True,
            ),
        )

        user = await self._get_user(user_id)
        sharing_summary = await self._build_sharing_summary(user_id)
        verification_summary = await self._build_verification_summary(user_id)

        return OwnerPassportResponse(
            profile=profile,
            trust_score=trust_score,
            vault=vault,
            passport_metadata=PassportMetadata(
                owner_user_id=user.id,
                profile_slug=user.profile_slug,
                is_email_verified=user.email_verified_at is not None,
                is_onboarding_complete=user.employment_onboarding_completed_at is not None,
                created_at=user.created_at,
                updated_at=user.updated_at,
                employment_onboarding_completed_at=user.employment_onboarding_completed_at,
            ),
            sharing_summary=sharing_summary,
            verification_summary=verification_summary,
        )

    async def _get_user(self, user_id: UUID) -> User:
        stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
        user = (await self._session.execute(stmt)).scalar_one()
        return user

    async def _build_sharing_summary(self, user_id: UUID) -> PassportSharingSummary:
        shares = list(
            (
                await self._session.execute(
                    select(PassportShareLink).where(PassportShareLink.owner_user_id == user_id)
                )
            )
            .scalars()
            .all()
        )

        total_links = len(shares)
        active_links = 0
        revoked_links = 0
        expired_links = 0
        latest_share_created_at = None
        last_viewed_at = None
        total_views = 0
        unique_views = 0
        now = datetime.now(tz=UTC)

        for share in shares:
            if latest_share_created_at is None or share.created_at > latest_share_created_at:
                latest_share_created_at = share.created_at
            if share.last_viewed_at and (last_viewed_at is None or share.last_viewed_at > last_viewed_at):
                last_viewed_at = share.last_viewed_at

            if share.revoked_at is not None:
                revoked_links += 1
            elif share.expires_at is not None and share.expires_at <= now:
                expired_links += 1
            else:
                active_links += 1

            total_views += await self._count_share_views(share.id)
            unique_views += await self._count_unique_share_views(share.id)

        return PassportSharingSummary(
            total_links=total_links,
            active_links=active_links,
            revoked_links=revoked_links,
            expired_links=expired_links,
            total_views=total_views,
            unique_views=unique_views,
            latest_share_created_at=latest_share_created_at,
            last_viewed_at=last_viewed_at,
        )

    async def _count_share_views(self, share_id: UUID) -> int:
        stmt = select(func.count()).select_from(PassportShareView).where(PassportShareView.share_id == share_id)
        return int((await self._session.execute(stmt)).scalar_one() or 0)

    async def _count_unique_share_views(self, share_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(PassportShareView)
            .where(PassportShareView.share_id == share_id, PassportShareView.is_unique_view.is_(True))
        )
        return int((await self._session.execute(stmt)).scalar_one() or 0)

    async def _build_verification_summary(self, user_id: UUID) -> PassportVerificationSummary:
        employments = await self._status_summary(Employment, Employment.created_by_user_id == user_id)
        educations = await self._status_summary(Education, Education.user_id == user_id)
        internships = await self._status_summary(Internship, Internship.user_id == user_id)
        freelance = await self._status_summary(FreelanceContract, FreelanceContract.user_id == user_id)
        gig_platforms = await self._status_summary(GigPlatform, GigPlatform.user_id == user_id)
        portfolio = await self._status_summary(PortfolioItem, PortfolioItem.user_id == user_id)
        certifications = await self._status_summary(Certification, Certification.user_id == user_id)
        user_documents = await self._status_summary(UserDocument, UserDocument.user_id == user_id)

        overall_statuses: dict[str, int] = {}
        sections = [
            employments,
            educations,
            internships,
            freelance,
            gig_platforms,
            portfolio,
            certifications,
            user_documents,
        ]
        total = 0
        for section in sections:
            total += section.total
            for status, count in section.statuses.items():
                overall_statuses[status] = overall_statuses.get(status, 0) + count

        overall = PassportSectionStatusSummary(total=total, statuses=overall_statuses)
        return PassportVerificationSummary(
            overall=overall,
            employments=employments,
            educations=educations,
            internships=internships,
            freelance=freelance,
            gig_platforms=gig_platforms,
            portfolio=portfolio,
            certifications=certifications,
            user_documents=user_documents,
        )

    async def _status_summary(self, model, owner_filter) -> PassportSectionStatusSummary:  # noqa: ANN001
        rows = list(
            (
                await self._session.execute(
                    select(model.verification_status, func.count())
                    .where(owner_filter, model.deleted_at.is_(None))
                    .group_by(model.verification_status)
                )
            ).all()
        )
        statuses = {str(status): int(count) for status, count in rows}
        total = sum(statuses.values())
        return PassportSectionStatusSummary(total=total, statuses=statuses)
