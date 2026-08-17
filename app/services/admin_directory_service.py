"""Read-only reviewer, organization, and candidate directories for Admin workflows."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.deps import CurrentUser
from app.auth.tokens import generate_opaque_refresh_raw, hash_refresh_token
from app.config import Settings
from app.core.constants import Role
from app.core.permissions import Permission, get_roles_with_permission, has_permission
from app.exceptions import ConflictError, NotFoundError
from app.integrations.email import get_email_sender
from app.models import (
    PassportShareLink,
    PassportShareView,
    PasswordResetToken,
    ProfileLanguage,
    ProfileLink,
    RefreshToken,
    User,
    UserAccountEvent,
    UserAdminNote,
    UserDocument,
)
from app.models.certification import Certification
from app.models.education import Education
from app.models.employment import Employment
from app.models.freelance_contract import FreelanceContract
from app.models.gig_platform import GigPlatform
from app.models.internship import Internship
from app.models.portfolio import PortfolioItem
from app.models.project import Project
from app.models.skill import Skill
from app.models.trust_score_snapshot import TrustScoreSnapshot
from app.models.verification_request import VerificationRequest
from app.models.verification_request_event import VerificationRequestEvent
from app.organization.enums import OrganizationType
from app.repositories.organization import OrganizationRepository
from app.repositories.password_reset_token import PasswordResetTokenRepository
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.schemas.admin_directory import (
    AdminOrganizationSearchItem,
    AdminOrganizationSearchPage,
    AdminReviewerPage,
    AdminReviewerResponse,
    AdminUserActionCapabilities,
    AdminUserActivityEvent,
    AdminUserCareerSummary,
    AdminUserDetailResponse,
    AdminUserDirectoryItem,
    AdminUserNoteCreateRequest,
    AdminUserNoteResponse,
    AdminUserPage,
    AdminUserPassportSummary,
    AdminUserRestoreRequest,
    AdminUserSessionResponse,
    AdminUserSuspendRequest,
    AdminUserTrustSummary,
    AdminUserVerificationBreakdown,
    AdminUserVerificationItem,
    AdminUserVerificationSummary,
)
from app.schemas.pagination import ListQueryParams
from app.verification_requests.enums import (
    VerificationRequestEventSource,
    VerificationRequestStatus,
    VerificationRequestType,
)


def normalize_organization_type(organization_type: OrganizationType | str) -> str:
    return (
        organization_type.value
        if isinstance(organization_type, OrganizationType)
        else organization_type
    )


COMPLETED_VERIFICATION_REQUEST_STATUSES = {
    VerificationRequestStatus.VERIFIED.value,
    VerificationRequestStatus.REJECTED.value,
    VerificationRequestStatus.UNABLE_TO_VERIFY.value,
    VerificationRequestStatus.CANCELLED.value,
    VerificationRequestStatus.EXPIRED.value,
}


def _enum_value(value: object | None) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def mask_email(value: str) -> str:
    local, _, domain = value.partition("@")
    if not domain:
        return "Redacted"
    shown = min(2, len(local))
    return f"{local[:shown]}{'*' * max(len(local) - shown, 0)}@{domain}"


def mask_phone(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 4:
        return "Redacted"
    return f"{value[:3]} {'•' * max(len(value) - 5, 0)}{value[-2:]}"


def admin_account_status(user: User) -> str:
    if user.deleted_at is not None:
        return "deleted"
    if user.suspended_at is not None or not user.is_active:
        return "suspended"
    return "active"


def build_display_name(user: User) -> str:
    if user.deleted_at is not None:
        return "Deleted Candidate"
    if user.full_name and user.full_name.strip():
        return user.full_name.strip()
    return "Unnamed Candidate"


def profile_completion_percentage(
    user: User,
    *,
    language_count: int,
    link_count: int,
) -> int:
    requirements = [
        bool((user.full_name or "").strip()),
        bool(user.avatar_key),
        bool((user.headline or "").strip()),
        bool((user.bio or "").strip()),
        bool(user.email_verified_at),
        bool(user.phone_verified_at),
        bool((user.location_city or user.location_country or user.location or "").strip()),
        language_count > 0,
        link_count > 0,
    ]
    return int(sum(requirements) * 100 / len(requirements))


def latest_datetime(*values: datetime | None) -> datetime | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def humanize(value: str | None) -> str:
    if not value:
        return "Unknown"
    return value.replace("_", " ").strip().title()


def build_linked_record_label(
    request: VerificationRequest,
    *,
    redacted: bool,
) -> str:
    request_type = _enum_value(request.request_type) or "request"
    if redacted:
        if request_type == VerificationRequestType.EMPLOYMENT.value:
            return "Employment record"
        if request_type == VerificationRequestType.EDUCATION.value:
            return "Education record"
        if request_type == VerificationRequestType.CERTIFICATION.value:
            return "Certification record"
        return f"{humanize(request_type)} record"

    if request.employment is not None:
        title = request.employment.job_title or "Employment"
        employer = request.employment.employer_legal_name or "Employer"
        return f"{title} at {employer}"
    if request.education is not None:
        degree = request.education.degree or "Education"
        institution = request.education.institution_name or "Institution"
        return f"{degree} at {institution}"
    if request.target_organization_name:
        return request.target_organization_name
    return humanize(request_type)


def build_verification_breakdown(summary: dict[str, int]) -> AdminUserVerificationBreakdown:
    return AdminUserVerificationBreakdown(
        total=sum(summary.values()),
        statuses={status: int(count) for status, count in summary.items()},
    )


def safe_detail_email(user: User) -> str:
    return "Redacted" if user.deleted_at is not None else user.email


def safe_detail_masked_email(user: User) -> str:
    return "Redacted" if user.deleted_at is not None else mask_email(user.email)


def onboarding_state(user: User) -> str:
    return "completed" if user.employment_onboarding_completed_at is not None else "incomplete"


def account_event_title(event_type: str) -> str:
    return event_type.replace("_", " ").strip().title()


def actor_display_name(actor: CurrentUser) -> str:
    if actor.full_name and actor.full_name.strip():
        return actor.full_name.strip()
    return actor.email


def session_status(row: RefreshToken, now: datetime) -> str:
    if row.revoked_at is not None:
        return "revoked"
    if row.expires_at <= now:
        return "expired"
    return "active"


def normalize_list_boundary(value: datetime | date | None, *, end_of_day: bool) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.combine(
        value,
        datetime.max.time() if end_of_day else datetime.min.time(),
        tzinfo=UTC,
    )


class AdminDirectoryService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._users = UserRepository(session)
        self._organizations = OrganizationRepository(session)
        self._refresh = RefreshTokenRepository(session)
        self._password_resets = PasswordResetTokenRepository(session)
        self._email = get_email_sender(settings, session=session)

    async def _require_candidate(self, user_public_id: UUID) -> User:
        user = (
            await self._session.execute(
                select(User).where(
                    User.id == user_public_id,
                    User.role == Role.USER.value,
                )
            )
        ).scalar_one_or_none()
        if user is None:
            raise NotFoundError("Candidate not found")
        return user

    def _build_capabilities(
        self,
        actor: CurrentUser,
        user: User,
    ) -> AdminUserActionCapabilities:
        deleted = user.deleted_at is not None
        suspended = admin_account_status(user) == "suspended"
        can_manage_notes = has_permission(actor.role, Permission.MANAGE_USER_NOTES)
        can_manage_accounts = has_permission(actor.role, Permission.MANAGE_USER_ACCOUNTS)
        can_manage_security = has_permission(actor.role, Permission.MANAGE_USER_SECURITY)
        return AdminUserActionCapabilities(
            view_notes=can_manage_notes,
            add_note=can_manage_notes and not deleted,
            suspend=can_manage_accounts and not deleted and not suspended,
            restore=can_manage_accounts and not deleted and suspended,
            revoke_sessions=can_manage_security and not deleted,
            send_password_reset=can_manage_security and not deleted and user.is_active,
        )

    async def _record_account_event(
        self,
        *,
        user_id: UUID,
        actor: CurrentUser,
        event_type: str,
        title: str,
        detail: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> UserAccountEvent:
        event = UserAccountEvent(
            user_id=user_id,
            actor_user_id=actor.id,
            actor_role=actor.role,
            actor_display_name=actor_display_name(actor),
            event_type=event_type,
            title=title,
            detail=detail,
            metadata_payload=metadata,
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def _session_activity(self, user_id: UUID) -> tuple[datetime | None, datetime | None]:
        row = (
            await self._session.execute(
                select(
                    func.max(RefreshToken.created_at),
                    func.max(RefreshToken.updated_at),
                ).where(RefreshToken.user_id == user_id)
            )
        ).one()
        return row[0], row[1]

    async def _suspended_by_display_name(self, user: User) -> str | None:
        if user.suspended_by_user_id is None:
            return None
        actor = await self._session.scalar(select(User).where(User.id == user.suspended_by_user_id))
        if actor is None:
            return None
        return build_display_name(actor)

    async def list_reviewers(self, params: ListQueryParams) -> AdminReviewerPage:
        users, total = await self._users.list_by_roles(
            get_roles_with_permission(Permission.REVIEW_VERIFICATION),
            search=params.search,
            offset=params.offset or 0,
            limit=params.limit or 20,
        )
        return AdminReviewerPage.create(
            items=[
                AdminReviewerResponse(
                    user_id=user.id,
                    full_name=user.full_name,
                    email=user.email,
                    role=user.role,
                )
                for user in users
            ],
            total=total,
            params=params,
        )

    async def search_organizations(self, params: ListQueryParams) -> AdminOrganizationSearchPage:
        organizations, total = await self._organizations.search_all(
            search=params.search,
            offset=params.offset or 0,
            limit=params.limit or 20,
        )
        return AdminOrganizationSearchPage.create(
            items=[
                AdminOrganizationSearchItem(
                    public_id=organization.public_id,
                    name=organization.name,
                    organization_type=normalize_organization_type(organization.organization_type),
                    verification_capabilities=list(organization.verification_capabilities or []),
                    registry_record_public_id=organization.registry_record.public_id
                    if organization.registry_record is not None
                    else None,
                    registry_resolution_status=(
                        "resolved" if organization.registry_record_id else "unresolved"
                    ),
                )
                for organization in organizations
            ],
            total=total,
            params=params,
        )

    async def list_users(self, params: ListQueryParams) -> AdminUserPage:
        filters = [User.role == Role.USER.value]
        search = (params.search or "").strip()
        if search:
            pattern = f"%{search}%"
            filters.append(
                or_(
                    User.full_name.ilike(pattern),
                    User.email.ilike(pattern),
                    User.phone.ilike(pattern),
                    User.profile_slug.ilike(pattern),
                    cast(User.id, String).ilike(pattern),
                )
            )

        created_after = normalize_list_boundary(params.created_after, end_of_day=False)
        if created_after is not None:
            filters.append(User.created_at >= created_after)
        created_before = normalize_list_boundary(params.created_before, end_of_day=True)
        if created_before is not None:
            filters.append(User.created_at <= created_before)

        requested_statuses = {
            item.strip().lower()
            for item in (params.status or "").split(",")
            if item.strip()
        }
        if requested_statuses:
            status_filters = []
            if "active" in requested_statuses:
                status_filters.append(User.deleted_at.is_(None) & User.is_active.is_(True))
            if "suspended" in requested_statuses or "inactive" in requested_statuses:
                status_filters.append(User.deleted_at.is_(None) & User.is_active.is_(False))
            if "deleted" in requested_statuses:
                status_filters.append(User.deleted_at.is_not(None))
            if status_filters:
                filters.append(or_(*status_filters))

        sort_field = (params.sort_by or "created_at").lower()
        sort_column = {
            "created_at": User.created_at,
            "updated_at": User.updated_at,
            "full_name": User.full_name,
            "email": User.email,
        }.get(sort_field, User.created_at)
        sort_clause = sort_column.asc() if params.sort_order == "asc" else sort_column.desc()

        total = int(
            (await self._session.scalar(select(func.count()).select_from(User).where(*filters)))
            or 0
        )
        rows = await self._session.execute(
            select(User)
            .where(*filters)
            .order_by(sort_clause, User.id.asc())
            .offset(params.offset or 0)
            .limit(params.limit or 20)
        )
        users = list(rows.scalars().all())
        user_ids = [user.id for user in users]

        language_counts = await self._count_by_owner(
            ProfileLanguage.user_id,
            ProfileLanguage,
            user_ids,
        )
        link_counts = await self._count_by_owner(ProfileLink.user_id, ProfileLink, user_ids)
        active_verifications, completed_verifications = await self._verification_counts(user_ids)
        career_counts = await self._career_counts(user_ids)
        active_share_counts, latest_share_updates = await self._share_stats(user_ids)
        latest_verification_updates = await self._latest_verification_activity(user_ids)
        trust_snapshots = await self._latest_trust_snapshots(user_ids)

        items = []
        for user in users:
            deleted = user.deleted_at is not None
            items.append(
                AdminUserDirectoryItem(
                    public_id=user.id,
                    display_name=build_display_name(user),
                    masked_email=safe_detail_masked_email(user),
                    account_status=admin_account_status(user),
                    created_at=user.created_at,
                    last_relevant_activity_at=latest_datetime(
                        user.updated_at,
                        latest_verification_updates.get(user.id),
                        None if deleted else latest_share_updates.get(user.id),
                    ),
                    profile_completion_percentage=0
                    if deleted
                    else profile_completion_percentage(
                        user,
                        language_count=language_counts.get(user.id, 0),
                        link_count=link_counts.get(user.id, 0),
                    ),
                    trust_score_overall=(
                        None if deleted else trust_snapshots.get(user.id, {}).get("overall")
                    ),
                    trust_score_status=(
                        None if deleted else trust_snapshots.get(user.id, {}).get("status")
                    ),
                    active_verification_count=active_verifications.get(user.id, 0),
                    completed_verification_count=completed_verifications.get(user.id, 0),
                    career_record_count=0 if deleted else career_counts.get(user.id, 0),
                    active_passport_share_count=(
                        0 if deleted else active_share_counts.get(user.id, 0)
                    ),
                    deleted_at=user.deleted_at,
                )
            )
        return AdminUserPage.create(items=items, total=total, params=params)

    async def get_user_detail(
        self,
        actor: CurrentUser,
        user_public_id: UUID,
    ) -> AdminUserDetailResponse:
        user = await self._require_candidate(user_public_id)
        deleted = user.deleted_at is not None
        language_counts = (
            {}
            if deleted
            else await self._count_by_owner(
                ProfileLanguage.user_id,
                ProfileLanguage,
                [user.id],
            )
        )
        link_counts = (
            {}
            if deleted
            else await self._count_by_owner(
                ProfileLink.user_id,
                ProfileLink,
                [user.id],
            )
        )

        trust = AdminUserTrustSummary() if deleted else await self._build_trust_summary(user.id)
        career_summary = (
            AdminUserCareerSummary() if deleted else await self._build_career_summary(user.id)
        )
        verification_summary = await self._build_verification_summary(user.id)
        verifications = await self._verification_items(user.id, redacted=deleted)
        passport = (
            AdminUserPassportSummary(ready=False)
            if deleted
            else await self._build_passport_summary(user)
        )
        sessions = [] if deleted else await self._session_items(user.id)
        notes = await self._note_items(user.id)
        activity = await self._activity_events(user.id)
        last_login_at, last_active_at = await self._session_activity(user.id)

        return AdminUserDetailResponse(
            public_id=user.id,
            display_name=build_display_name(user),
            account_status=admin_account_status(user),
            profile_slug=None if deleted else user.profile_slug,
            candidate_type="candidate",
            email=safe_detail_email(user),
            masked_email=safe_detail_masked_email(user),
            phone=None if deleted else user.phone,
            masked_phone=None if deleted else mask_phone(user.phone),
            headline=None if deleted else user.headline,
            current_role=None if deleted else user.current_role,
            location=None if deleted else user.location,
            created_at=user.created_at,
            updated_at=user.updated_at,
            last_login_at=last_login_at,
            last_active_at=last_active_at,
            deleted_at=user.deleted_at,
            suspended_at=user.suspended_at,
            suspension_reason=user.suspension_reason,
            suspended_by_display_name=await self._suspended_by_display_name(user),
            email_verified=False if deleted else user.email_verified_at is not None,
            phone_verified=False if deleted else user.phone_verified_at is not None,
            onboarding_completed=(
                False if deleted else user.employment_onboarding_completed_at is not None
            ),
            onboarding_state=onboarding_state(user),
            profile_completion_percentage=0
            if deleted
            else profile_completion_percentage(
                user,
                language_count=language_counts.get(user.id, 0),
                link_count=link_counts.get(user.id, 0),
            ),
            trust=trust,
            career_summary=career_summary,
            verification_summary=verification_summary,
            verifications=verifications,
            passport=passport,
            sessions=sessions,
            notes=notes,
            capabilities=self._build_capabilities(actor, user),
            activity=activity,
        )

    async def _session_items(self, user_id: UUID) -> list[AdminUserSessionResponse]:
        now = datetime.now(tz=UTC)
        rows = await self._session.execute(
            select(RefreshToken)
            .where(RefreshToken.user_id == user_id)
            .order_by(RefreshToken.created_at.desc(), RefreshToken.id.desc())
            .limit(20)
        )
        return [
            AdminUserSessionResponse(
                public_id=row.id,
                created_at=row.created_at,
                expires_at=row.expires_at,
                last_active_at=row.updated_at,
                revoked_at=row.revoked_at,
                status=session_status(row, now),
            )
            for row in rows.scalars().all()
        ]

    async def _note_items(self, user_id: UUID) -> list[AdminUserNoteResponse]:
        rows = await self._session.execute(
            select(UserAdminNote)
            .where(UserAdminNote.user_id == user_id)
            .order_by(UserAdminNote.created_at.desc(), UserAdminNote.id.desc())
            .limit(50)
        )
        return [
            AdminUserNoteResponse(
                public_id=note.public_id,
                created_at=note.created_at,
                author_display_name=note.author_display_name,
                author_role=note.author_role,
                body=note.body,
            )
            for note in rows.scalars().all()
        ]

    async def add_note(
        self,
        actor: CurrentUser,
        user_public_id: UUID,
        payload: AdminUserNoteCreateRequest,
    ) -> AdminUserNoteResponse:
        user = await self._require_candidate(user_public_id)
        if user.deleted_at is not None:
            raise ConflictError("Cannot add notes to a deleted candidate account")

        note = UserAdminNote(
            user_id=user.id,
            author_user_id=actor.id,
            author_role=actor.role,
            author_display_name=actor_display_name(actor),
            body=payload.body,
        )
        self._session.add(note)
        await self._session.flush()
        await self._record_account_event(
            user_id=user.id,
            actor=actor,
            event_type="admin_note_added",
            title="Internal admin note added",
            detail=payload.body[:200],
            metadata={"note_public_id": str(note.public_id)},
        )
        await self._session.commit()
        return AdminUserNoteResponse(
            public_id=note.public_id,
            created_at=note.created_at,
            author_display_name=note.author_display_name,
            author_role=note.author_role,
            body=note.body,
        )

    async def suspend_user(
        self,
        actor: CurrentUser,
        user_public_id: UUID,
        payload: AdminUserSuspendRequest,
    ) -> AdminUserDetailResponse:
        user = await self._require_candidate(user_public_id)
        if user.deleted_at is not None:
            raise ConflictError("Deleted candidate accounts cannot be suspended")
        if admin_account_status(user) == "suspended":
            raise ConflictError("Candidate account is already suspended")

        now = datetime.now(tz=UTC)
        user.is_active = False
        user.suspended_at = now
        user.suspension_reason = payload.reason
        user.suspended_by_user_id = actor.id

        shares = list(
            (
                await self._session.execute(
                    select(PassportShareLink).where(
                        PassportShareLink.owner_user_id == user.id,
                        PassportShareLink.revoked_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for share in shares:
            share.revoked_at = now

        await self._refresh.revoke_all_for_user(user.id)
        await self._record_account_event(
            user_id=user.id,
            actor=actor,
            event_type="account_suspended",
            title="Candidate account suspended",
            detail=payload.reason,
            metadata={"revoked_passport_links": len(shares)},
        )
        await self._session.commit()
        return await self.get_user_detail(actor, user_public_id)

    async def restore_user(
        self,
        actor: CurrentUser,
        user_public_id: UUID,
        payload: AdminUserRestoreRequest,
    ) -> AdminUserDetailResponse:
        user = await self._require_candidate(user_public_id)
        if user.deleted_at is not None:
            raise ConflictError("Deleted candidate accounts cannot be restored")
        if admin_account_status(user) != "suspended":
            raise ConflictError("Candidate account is not suspended")

        user.is_active = True
        user.suspended_at = None
        user.suspension_reason = None
        user.suspended_by_user_id = None
        await self._record_account_event(
            user_id=user.id,
            actor=actor,
            event_type="account_restored",
            title="Candidate account restored",
            detail=payload.reason,
        )
        await self._session.commit()
        return await self.get_user_detail(actor, user_public_id)

    async def revoke_session(
        self,
        actor: CurrentUser,
        user_public_id: UUID,
        session_public_id: UUID,
    ) -> AdminUserDetailResponse:
        user = await self._require_candidate(user_public_id)
        if user.deleted_at is not None:
            raise ConflictError("Deleted candidate accounts do not have revocable sessions")

        row = await self._session.scalar(
            select(RefreshToken).where(
                RefreshToken.user_id == user.id,
                RefreshToken.id == session_public_id,
            )
        )
        if row is None:
            raise NotFoundError("Session not found")
        if session_status(row, datetime.now(tz=UTC)) != "active":
            raise ConflictError("Session is already inactive")

        await self._refresh.revoke(row.id)
        await self._record_account_event(
            user_id=user.id,
            actor=actor,
            event_type="session_revoked",
            title="Candidate session revoked",
            detail=str(row.family_id),
            metadata={"session_public_id": str(row.id)},
        )
        await self._session.commit()
        return await self.get_user_detail(actor, user_public_id)

    async def revoke_all_sessions(
        self,
        actor: CurrentUser,
        user_public_id: UUID,
    ) -> AdminUserDetailResponse:
        user = await self._require_candidate(user_public_id)
        if user.deleted_at is not None:
            raise ConflictError("Deleted candidate accounts do not have revocable sessions")

        active_count = int(
            (
                await self._session.scalar(
                    select(func.count())
                    .select_from(RefreshToken)
                    .where(
                        RefreshToken.user_id == user.id,
                        RefreshToken.revoked_at.is_(None),
                        RefreshToken.expires_at > datetime.now(tz=UTC),
                    )
                )
            )
            or 0
        )
        await self._refresh.revoke_all_for_user(user.id)
        await self._record_account_event(
            user_id=user.id,
            actor=actor,
            event_type="all_sessions_revoked",
            title="All candidate sessions revoked",
            detail=f"{active_count} active session(s) revoked",
            metadata={"revoked_sessions": active_count},
        )
        await self._session.commit()
        return await self.get_user_detail(actor, user_public_id)

    async def initiate_password_reset(
        self,
        actor: CurrentUser,
        user_public_id: UUID,
    ) -> AdminUserDetailResponse:
        user = await self._require_candidate(user_public_id)
        if user.deleted_at is not None:
            raise ConflictError("Deleted candidate accounts cannot receive password reset emails")
        if user.email_verified_at is None:
            raise ConflictError("Password reset requires a verified candidate email address")
        if not user.is_active:
            raise ConflictError("Password reset is unavailable for suspended candidate accounts")

        now = datetime.now(tz=UTC)
        raw_token = generate_opaque_refresh_raw()
        token_hash = hash_refresh_token(raw_token)
        expires_at = now + timedelta(minutes=self._settings.password_reset_token_ttl_minutes)

        await self._password_resets.mark_all_active_for_user_used(user.id, used_at=now)
        await self._password_resets.create(
            PasswordResetToken(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=expires_at,
                used_at=None,
            )
        )

        try:
            await self._email.send_password_reset(
                to_email=user.email,
                reset_token=raw_token,
                ttl_minutes=self._settings.password_reset_token_ttl_minutes,
            )
        except Exception as exc:
            await self._session.rollback()
            raise ConflictError(
                f"Password reset email could not be sent ({type(exc).__name__})"
            ) from exc

        await self._record_account_event(
            user_id=user.id,
            actor=actor,
            event_type="password_reset_initiated",
            title="Password reset email sent",
            detail="Admin initiated secure password reset flow",
        )
        await self._session.commit()
        return await self.get_user_detail(actor, user_public_id)

    async def _count_by_owner(self, owner_field, model, user_ids: list[UUID]) -> dict[UUID, int]:  # noqa: ANN001
        if not user_ids:
            return {}
        filters = [owner_field.in_(user_ids)]
        if hasattr(model, "deleted_at"):
            filters.append(model.deleted_at.is_(None))
        rows = await self._session.execute(
            select(owner_field, func.count())
            .select_from(model)
            .where(*filters)
            .group_by(owner_field)
        )
        return {owner_user_id: int(total or 0) for owner_user_id, total in rows.all()}

    async def _verification_counts(
        self,
        user_ids: list[UUID],
    ) -> tuple[dict[UUID, int], dict[UUID, int]]:
        if not user_ids:
            return {}, {}
        rows = await self._session.execute(
            select(VerificationRequest.subject_user_id, VerificationRequest.status, func.count())
            .where(VerificationRequest.subject_user_id.in_(user_ids))
            .group_by(VerificationRequest.subject_user_id, VerificationRequest.status)
        )
        active: dict[UUID, int] = {}
        completed: dict[UUID, int] = {}
        for user_id, status, count in rows.all():
            key = _enum_value(status) or "unknown"
            bucket = completed if key in COMPLETED_VERIFICATION_REQUEST_STATUSES else active
            bucket[user_id] = bucket.get(user_id, 0) + int(count or 0)
        return active, completed

    async def _career_counts(self, user_ids: list[UUID]) -> dict[UUID, int]:
        totals = {user_id: 0 for user_id in user_ids}
        if not user_ids:
            return totals
        buckets = [
            await self._count_by_owner(Employment.created_by_user_id, Employment, user_ids),
            await self._count_by_owner(Education.user_id, Education, user_ids),
            await self._count_by_owner(Internship.user_id, Internship, user_ids),
            await self._count_by_owner(FreelanceContract.user_id, FreelanceContract, user_ids),
            await self._count_by_owner(GigPlatform.user_id, GigPlatform, user_ids),
            await self._count_by_owner(PortfolioItem.user_id, PortfolioItem, user_ids),
            await self._count_by_owner(Certification.user_id, Certification, user_ids),
            await self._count_by_owner(Skill.user_id, Skill, user_ids),
            await self._count_by_owner(Project.user_id, Project, user_ids),
            await self._count_by_owner(UserDocument.user_id, UserDocument, user_ids),
        ]
        for bucket in buckets:
            for user_id, count in bucket.items():
                totals[user_id] = totals.get(user_id, 0) + count
        return totals

    async def _build_career_summary(self, user_id: UUID) -> AdminUserCareerSummary:
        employments = await self._count_by_owner(
            Employment.created_by_user_id,
            Employment,
            [user_id],
        )
        educations = await self._count_by_owner(Education.user_id, Education, [user_id])
        internships = await self._count_by_owner(Internship.user_id, Internship, [user_id])
        freelance = await self._count_by_owner(
            FreelanceContract.user_id,
            FreelanceContract,
            [user_id],
        )
        gig_platforms = await self._count_by_owner(GigPlatform.user_id, GigPlatform, [user_id])
        portfolio = await self._count_by_owner(PortfolioItem.user_id, PortfolioItem, [user_id])
        certifications = await self._count_by_owner(Certification.user_id, Certification, [user_id])
        skills = await self._count_by_owner(Skill.user_id, Skill, [user_id])
        projects = await self._count_by_owner(Project.user_id, Project, [user_id])
        user_documents = await self._count_by_owner(UserDocument.user_id, UserDocument, [user_id])
        summary = AdminUserCareerSummary(
            employments=employments.get(user_id, 0),
            educations=educations.get(user_id, 0),
            internships=internships.get(user_id, 0),
            freelance=freelance.get(user_id, 0),
            gig_platforms=gig_platforms.get(user_id, 0),
            portfolio=portfolio.get(user_id, 0),
            certifications=certifications.get(user_id, 0),
            skills=skills.get(user_id, 0),
            projects=projects.get(user_id, 0),
            user_documents=user_documents.get(user_id, 0),
        )
        summary.total_items = (
            summary.employments
            + summary.educations
            + summary.internships
            + summary.freelance
            + summary.gig_platforms
            + summary.portfolio
            + summary.certifications
            + summary.skills
            + summary.projects
            + summary.user_documents
        )
        return summary

    async def _share_stats(
        self,
        user_ids: list[UUID],
    ) -> tuple[dict[UUID, int], dict[UUID, datetime | None]]:
        if not user_ids:
            return {}, {}
        rows = await self._session.execute(
            select(
                PassportShareLink.owner_user_id,
                func.count().filter(PassportShareLink.revoked_at.is_(None)),
                func.max(PassportShareLink.updated_at),
            )
            .where(PassportShareLink.owner_user_id.in_(user_ids))
            .group_by(PassportShareLink.owner_user_id)
        )
        counts: dict[UUID, int] = {}
        updates: dict[UUID, datetime | None] = {}
        for user_id, count, updated_at in rows.all():
            counts[user_id] = int(count or 0)
            updates[user_id] = updated_at
        return counts, updates

    async def _latest_verification_activity(
        self,
        user_ids: list[UUID],
    ) -> dict[UUID, datetime | None]:
        if not user_ids:
            return {}
        rows = await self._session.execute(
            select(VerificationRequest.subject_user_id, func.max(VerificationRequest.updated_at))
            .where(VerificationRequest.subject_user_id.in_(user_ids))
            .group_by(VerificationRequest.subject_user_id)
        )
        return {user_id: updated_at for user_id, updated_at in rows.all()}

    async def _latest_trust_snapshots(
        self,
        user_ids: list[UUID],
    ) -> dict[UUID, dict[str, object | None]]:
        if not user_ids:
            return {}
        rows = await self._session.execute(
            select(TrustScoreSnapshot)
            .where(TrustScoreSnapshot.user_id.in_(user_ids))
            .order_by(TrustScoreSnapshot.user_id.asc(), TrustScoreSnapshot.calculated_at.desc())
        )
        snapshots: dict[UUID, dict[str, object | None]] = {}
        for snapshot in rows.scalars().all():
            if snapshot.user_id in snapshots:
                continue
            snapshots[snapshot.user_id] = {
                "overall": snapshot.overall_score,
                "status": snapshot.status,
            }
        return snapshots

    async def _build_trust_summary(self, user_id: UUID) -> AdminUserTrustSummary:
        snapshot = (
            await self._session.execute(
                select(TrustScoreSnapshot)
                .where(TrustScoreSnapshot.user_id == user_id)
                .order_by(TrustScoreSnapshot.calculated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if snapshot is None:
            return AdminUserTrustSummary()
        return AdminUserTrustSummary(
            overall=snapshot.overall_score,
            status=snapshot.status,
            verification_completeness_percentage=snapshot.verification_completeness_percentage,
            last_calculated_at=snapshot.calculated_at,
        )

    async def _build_verification_summary(self, user_id: UUID) -> AdminUserVerificationSummary:
        rows = await self._session.execute(
            select(VerificationRequest.request_type, VerificationRequest.status, func.count())
            .where(VerificationRequest.subject_user_id == user_id)
            .group_by(VerificationRequest.request_type, VerificationRequest.status)
        )
        overall: dict[str, int] = {}
        by_type: dict[str, dict[str, int]] = {
            VerificationRequestType.EMPLOYMENT.value: {},
            VerificationRequestType.EDUCATION.value: {},
            VerificationRequestType.CERTIFICATION.value: {},
        }
        for request_type, status, count in rows.all():
            request_key = _enum_value(request_type) or "unknown"
            status_key = _enum_value(status) or "unknown"
            overall[status_key] = overall.get(status_key, 0) + int(count or 0)
            if request_key in by_type:
                bucket = by_type[request_key]
                bucket[status_key] = bucket.get(status_key, 0) + int(count or 0)
        return AdminUserVerificationSummary(
            overall=build_verification_breakdown(overall),
            employments=build_verification_breakdown(by_type[VerificationRequestType.EMPLOYMENT.value]),
            educations=build_verification_breakdown(by_type[VerificationRequestType.EDUCATION.value]),
            certifications=build_verification_breakdown(by_type[VerificationRequestType.CERTIFICATION.value]),
        )

    async def _verification_items(
        self,
        user_id: UUID,
        *,
        redacted: bool,
    ) -> list[AdminUserVerificationItem]:
        rows = await self._session.execute(
            select(VerificationRequest)
            .where(VerificationRequest.subject_user_id == user_id)
            .options(
                selectinload(VerificationRequest.organization),
                selectinload(VerificationRequest.employment),
                selectinload(VerificationRequest.education),
            )
            .order_by(VerificationRequest.updated_at.desc(), VerificationRequest.created_at.desc())
        )
        items = []
        for request in rows.scalars().all():
            items.append(
                AdminUserVerificationItem(
                    public_id=request.public_id,
                    request_type=_enum_value(request.request_type) or "unknown",
                    status=_enum_value(request.status) or "unknown",
                    employment_public_id=request.employment_id,
                    education_public_id=request.education_id,
                    organization_public_id=(
                        request.organization.public_id
                        if request.organization is not None
                        else None
                    ),
                    organization_name=(
                        request.organization.name
                        if request.organization is not None
                        else None
                    ),
                    linked_record_label=build_linked_record_label(request, redacted=redacted),
                    created_at=request.created_at,
                    submitted_at=(
                        request.accepted_at
                        or request.candidate_response_submitted_at
                        or request.created_at
                    ),
                    updated_at=request.updated_at,
                )
            )
        return items

    async def _build_passport_summary(self, user: User) -> AdminUserPassportSummary:
        shares = list(
            (
                await self._session.execute(
                    select(PassportShareLink)
                    .where(PassportShareLink.owner_user_id == user.id)
                    .order_by(PassportShareLink.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        now = datetime.now(tz=UTC)
        active_links = 0
        revoked_links = 0
        expired_links = 0
        latest_share_created_at = None
        last_viewed_at = None
        share_ids = [share.id for share in shares]
        for share in shares:
            latest_share_created_at = latest_datetime(latest_share_created_at, share.created_at)
            last_viewed_at = latest_datetime(last_viewed_at, share.last_viewed_at)
            if share.revoked_at is not None:
                revoked_links += 1
            elif share.expires_at is not None and share.expires_at <= now:
                expired_links += 1
            else:
                active_links += 1

        total_views = 0
        unique_views = 0
        if share_ids:
            total_views = int(
                (
                    await self._session.scalar(
                        select(func.count()).select_from(PassportShareView).where(PassportShareView.share_id.in_(share_ids))
                    )
                )
                or 0
            )
            unique_views = int(
                (
                    await self._session.scalar(
                        select(func.count())
                        .select_from(PassportShareView)
                        .where(
                            PassportShareView.share_id.in_(share_ids),
                            PassportShareView.is_unique_view.is_(True),
                        )
                    )
                )
                or 0
            )
        return AdminUserPassportSummary(
            ready=(
                user.email_verified_at is not None
                and user.phone_verified_at is not None
                and user.employment_onboarding_completed_at is not None
            ),
            active_links=active_links,
            revoked_links=revoked_links,
            expired_links=expired_links,
            total_views=total_views,
            unique_views=unique_views,
            latest_share_created_at=latest_share_created_at,
            last_viewed_at=last_viewed_at,
        )

    async def _activity_events(self, user_id: UUID) -> list[AdminUserActivityEvent]:
        verification_rows = await self._session.execute(
            select(VerificationRequestEvent)
            .join(
                VerificationRequest,
                VerificationRequest.id == VerificationRequestEvent.verification_request_id,
            )
            .where(VerificationRequest.subject_user_id == user_id)
            .order_by(VerificationRequestEvent.created_at.desc())
            .limit(50)
        )
        account_rows = await self._session.execute(
            select(UserAccountEvent)
            .where(UserAccountEvent.user_id == user_id)
            .order_by(UserAccountEvent.created_at.desc(), UserAccountEvent.id.desc())
            .limit(50)
        )

        events: list[AdminUserActivityEvent] = []
        for event in verification_rows.scalars().all():
            detail = None
            previous_status = _enum_value(event.previous_status)
            new_status = _enum_value(event.new_status)
            if previous_status and new_status:
                detail = f"{humanize(previous_status)} -> {humanize(new_status)}"
            elif new_status:
                detail = humanize(new_status)
            events.append(
                AdminUserActivityEvent(
                    public_id=event.public_id,
                    occurred_at=event.created_at,
                    kind=(
                        _enum_value(event.event_source)
                        or VerificationRequestEventSource.SYSTEM.value
                    ),
                    title=humanize(event.event_type),
                    detail=detail,
                )
            )
        for event in account_rows.scalars().all():
            events.append(
                AdminUserActivityEvent(
                    public_id=event.public_id,
                    occurred_at=event.created_at,
                    kind=event.event_type,
                    title=event.title,
                    detail=event.detail,
                    actor_display_name=event.actor_display_name,
                    actor_role=event.actor_role,
                )
            )
        events.sort(key=lambda item: (item.occurred_at, str(item.public_id)), reverse=True)
        return events[:100]
