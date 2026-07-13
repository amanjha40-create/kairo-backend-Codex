"""Backend-owned Trust Passport aggregation services."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import (
    Certification,
    Education,
    Employment,
    EmploymentDocument,
    GigPlatform,
    Internship,
    PassportShareLink,
    PassportShareView,
    PortfolioItem,
    User,
    UserDocument,
    VerificationAuditEvent,
)
from app.models.freelance_contract import FreelanceContract
from app.schemas.passport_engine import (
    DashboardActivePassportShares,
    DashboardActivityItem,
    DashboardResponse,
    DashboardShareAnalyticsItem,
    DashboardShareSummaryItem,
    DashboardVaultSummary,
    OnboardingStatusResponse,
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

    async def get_dashboard(self, user_id: UUID) -> DashboardResponse:
        user = await self._get_user(user_id)
        trust_score = await self._trust.calculate_trust_score(user_id)
        verification_summary = await self._build_verification_summary(user_id)
        profile_completion = await self._build_onboarding_status(user)
        active_passport_shares = await self._build_active_passport_shares(user_id)
        recent_share_analytics = await self._build_recent_share_analytics(user_id)
        recent_activity = await self._build_recent_activity(user_id)

        return DashboardResponse(
            profile_completion=profile_completion,
            trust_score=trust_score,
            verification_summary=verification_summary,
            vault_summary=self._build_vault_summary(verification_summary),
            active_passport_shares=active_passport_shares,
            recent_share_analytics=recent_share_analytics,
            recent_activity=recent_activity,
        )

    async def get_onboarding_status(self, user_id: UUID) -> OnboardingStatusResponse:
        user = await self._get_user(user_id)
        return await self._build_onboarding_status(user)

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

    async def _build_onboarding_status(self, user: User) -> OnboardingStatusResponse:
        email_verified = user.email_verified_at is not None
        phone_verified = user.phone_verified_at is not None
        minimum_profile_complete = all(
            [
                self._has_value(user.full_name),
                self._has_value(user.phone),
                self._has_value(user.headline),
                self._has_value(user.current_role),
                self._has_value(user.industry),
                user.years_of_experience is not None,
            ]
        )
        passport_ready = email_verified and phone_verified and minimum_profile_complete

        requirements: list[tuple[str, bool]] = [
            ("verify_email", email_verified),
            ("verify_phone", phone_verified),
            ("headline", self._has_value(user.headline)),
            ("current_role", self._has_value(user.current_role)),
            ("industry", self._has_value(user.industry)),
            ("years_of_experience", user.years_of_experience is not None),
        ]

        completed_steps: list[str] = []
        if email_verified:
            completed_steps.append("verify_email")
        if phone_verified:
            completed_steps.append("verify_phone")
        if minimum_profile_complete:
            completed_steps.append("complete_profile")

        missing_requirements = [step for step, done in requirements if not done]
        completion_percentage = int((sum(1 for _, done in requirements if done) / len(requirements)) * 100)
        if not email_verified or not phone_verified:
            current_step = "verify_identity"
            next_step = "complete_profile" if email_verified and phone_verified else "verify_identity"
        elif not minimum_profile_complete:
            current_step = "complete_profile"
            next_step = "complete_profile"
        else:
            current_step = "complete"
            next_step = None

        return OnboardingStatusResponse(
            current_step=current_step,
            email_verified=email_verified,
            phone_verified=phone_verified,
            passport_ready=passport_ready,
            completed_steps=completed_steps,
            missing_requirements=missing_requirements,
            next_recommended_step=next_step,
            completion_percentage=completion_percentage,
            is_onboarding_complete=passport_ready or user.employment_onboarding_completed_at is not None,
        )

    def _build_vault_summary(
        self,
        verification_summary: PassportVerificationSummary,
    ) -> DashboardVaultSummary:
        employments = verification_summary.employments.total
        educations = verification_summary.educations.total
        internships = verification_summary.internships.total
        freelance = verification_summary.freelance.total
        gig_platforms = verification_summary.gig_platforms.total
        portfolio = verification_summary.portfolio.total
        certifications = verification_summary.certifications.total
        user_documents = verification_summary.user_documents.total

        return DashboardVaultSummary(
            total_items=(
                employments
                + educations
                + internships
                + freelance
                + gig_platforms
                + portfolio
                + certifications
                + user_documents
            ),
            employments=employments,
            educations=educations,
            internships=internships,
            freelance=freelance,
            gig_platforms=gig_platforms,
            portfolio=portfolio,
            certifications=certifications,
            user_documents=user_documents,
        )

    async def _build_active_passport_shares(self, user_id: UUID) -> DashboardActivePassportShares:
        shares = await self._list_shares(user_id)
        active_items = [
            DashboardShareSummaryItem(
                share_id=share.id,
                label=share.label,
                state=self._share_state(share),
                expires_at=share.expires_at,
                last_viewed_at=share.last_viewed_at,
                created_at=share.created_at,
            )
            for share in shares
            if self._share_state(share) == "active"
        ]

        return DashboardActivePassportShares(
            count=len(active_items),
            items=active_items[:5],
        )

    async def _build_recent_share_analytics(self, user_id: UUID) -> list[DashboardShareAnalyticsItem]:
        shares = await self._list_shares(user_id)
        viewed = [share for share in shares if share.last_viewed_at is not None]
        viewed.sort(key=lambda share: share.last_viewed_at or share.created_at, reverse=True)

        items: list[DashboardShareAnalyticsItem] = []
        for share in viewed[:5]:
            items.append(
                DashboardShareAnalyticsItem(
                    share_id=share.id,
                    label=share.label,
                    state=self._share_state(share),
                    total_views=await self._count_share_views(share.id),
                    unique_views=await self._count_unique_share_views(share.id),
                    last_viewed_at=share.last_viewed_at,
                )
            )

        return items

    async def _build_recent_activity(self, user_id: UUID) -> list[DashboardActivityItem]:
        items = await self._build_recent_verification_activity(user_id)
        items.extend(await self._build_recent_share_activity(user_id))
        items.sort(key=lambda item: item.occurred_at, reverse=True)
        return items[:10]

    async def _build_recent_verification_activity(self, user_id: UUID) -> list[DashboardActivityItem]:
        stmt = (
            select(VerificationAuditEvent, Employment)
            .join(Employment, Employment.id == VerificationAuditEvent.employment_id)
            .where(
                Employment.created_by_user_id == user_id,
                Employment.deleted_at.is_(None),
            )
            .order_by(VerificationAuditEvent.created_at.desc())
            .limit(10)
        )
        rows = (await self._session.execute(stmt)).all()

        return [
            DashboardActivityItem(
                occurred_at=audit_row.created_at,
                category="verification",
                action=audit_row.action,
                title=self._humanize_action(audit_row.action),
                detail=employment.employer_legal_name,
                subject_id=employment.id,
            )
            for audit_row, employment in rows
        ]

    async def _build_recent_share_activity(self, user_id: UUID) -> list[DashboardActivityItem]:
        shares = await self._list_shares(user_id)
        items: list[DashboardActivityItem] = []
        for share in shares[:10]:
            share_label = share.label or "Trust Passport share"
            items.append(
                DashboardActivityItem(
                    occurred_at=share.created_at,
                    category="passport_share",
                    action="share_created",
                    title="Trust Passport share created",
                    detail=share_label,
                    subject_id=share.id,
                )
            )
            if share.revoked_at is not None:
                items.append(
                    DashboardActivityItem(
                        occurred_at=share.revoked_at,
                        category="passport_share",
                        action="share_revoked",
                        title="Trust Passport share revoked",
                        detail=share_label,
                        subject_id=share.id,
                    )
                )
            if share.last_viewed_at is not None:
                items.append(
                    DashboardActivityItem(
                        occurred_at=share.last_viewed_at,
                        category="passport_share",
                        action="share_viewed",
                        title="Trust Passport share viewed",
                        detail=share_label,
                        subject_id=share.id,
                    )
                )
        return items

    async def _list_shares(self, user_id: UUID) -> list[PassportShareLink]:
        stmt = (
            select(PassportShareLink)
            .where(PassportShareLink.owner_user_id == user_id)
            .order_by(PassportShareLink.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def _count_work_history(self, user_id: UUID) -> int:
        return (
            await self._count_owned(Employment, Employment.created_by_user_id == user_id)
            + await self._count_owned(Internship, Internship.user_id == user_id)
            + await self._count_owned(FreelanceContract, FreelanceContract.user_id == user_id)
            + await self._count_owned(GigPlatform, GigPlatform.user_id == user_id)
        )

    async def _count_supporting_documents(self, user_id: UUID) -> int:
        return (
            await self._count_owned(UserDocument, UserDocument.user_id == user_id)
            + await self._count_employment_documents(user_id)
        )

    async def _count_owned(self, model, owner_filter) -> int:  # noqa: ANN001
        stmt = select(func.count()).select_from(model).where(owner_filter, model.deleted_at.is_(None))
        return int((await self._session.execute(stmt)).scalar_one() or 0)

    async def _count_employment_documents(self, user_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(EmploymentDocument)
            .join(Employment, Employment.id == EmploymentDocument.employment_id)
            .where(
                Employment.created_by_user_id == user_id,
                Employment.deleted_at.is_(None),
                EmploymentDocument.deleted_at.is_(None),
            )
        )
        return int((await self._session.execute(stmt)).scalar_one() or 0)

    def _share_state(self, share: PassportShareLink) -> str:
        if share.revoked_at is not None:
            return "revoked"
        if share.expires_at is not None and share.expires_at <= datetime.now(tz=UTC):
            return "expired"
        return "active"

    def _humanize_action(self, action: str) -> str:
        return action.replace("_", " ").strip().title()

    def _has_value(self, value: str | None) -> bool:
        return bool(value and value.strip())
