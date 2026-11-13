"""Admin Client search, detail, activity, and company-record operations."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import String, and_, cast, exists, func, literal, or_, select, union_all
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, joinedload, selectinload

from app.exceptions import ConflictError, NotFoundError
from app.models.organization import Organization
from app.models.organization_activity_event import OrganizationActivityEvent
from app.models.organization_member import OrganizationMember
from app.models.organization_person import OrganizationPerson
from app.models.refresh_token import RefreshToken
from app.models.trust_invitation import TrustInvitation
from app.models.trust_invitation_event import TrustInvitationEvent
from app.models.trust_registry_domain import TrustRegistryDomain
from app.models.trust_registry_record import TrustRegistryRecord
from app.models.user import User
from app.models.verification_request import VerificationRequest
from app.models.verification_request_event import VerificationRequestEvent
from app.organization.enums import OrganizationRole
from app.schemas.admin_organization import (
    AdminOrganizationActivityItem,
    AdminOrganizationActivityPage,
    AdminOrganizationCompanyRecordConnectRequest,
    AdminOrganizationCompanyRecordCreateRequest,
    AdminOrganizationCompanyRecordResponse,
    AdminOrganizationDetailResponse,
    AdminOrganizationListItem,
    AdminOrganizationListParams,
    AdminOrganizationOverviewResponse,
    AdminOrganizationPage,
    AdminOrganizationPeoplePage,
    AdminOrganizationPersonItem,
    AdminOrganizationTeamItem,
    AdminOrganizationTeamPage,
    AdminOrganizationVerificationItem,
    AdminOrganizationVerificationListParams,
    AdminOrganizationVerificationPage,
)
from app.schemas.pagination import ListQueryParams
from app.services.trust_registry_service import TrustRegistryCodeService
from app.verification_requests.enums import VerificationRequestStatus

PENDING_STATUSES = {
    VerificationRequestStatus.DRAFT.value,
    VerificationRequestStatus.PENDING_SUBJECT_ACCEPTANCE.value,
    VerificationRequestStatus.ACCEPTED.value,
    VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION.value,
    VerificationRequestStatus.PENDING_ADMIN_REVIEW.value,
    VerificationRequestStatus.AWAITING_SUBJECT_CORRECTIONS.value,
    VerificationRequestStatus.PENDING_ADMIN_RE_REVIEW.value,
}
IN_PROGRESS_STATUSES = {
    VerificationRequestStatus.APPROVED_FOR_ORGANIZATION_VERIFICATION.value,
    VerificationRequestStatus.PENDING_ORGANIZATION_RESOLUTION.value,
    VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE.value,
    VerificationRequestStatus.IN_PROGRESS.value,
    VerificationRequestStatus.AWAITING_INFORMATION.value,
    VerificationRequestStatus.PENDING_ADMIN_QUALITY_REVIEW.value,
}
NEEDS_ATTENTION_STATUSES = {
    VerificationRequestStatus.REJECTED.value,
    VerificationRequestStatus.UNABLE_TO_VERIFY.value,
    VerificationRequestStatus.EXPIRED.value,
}
EXCLUDED_FROM_COMPLETION_RATE = {
    VerificationRequestStatus.DRAFT.value,
    VerificationRequestStatus.CANCELLED.value,
    VerificationRequestStatus.WITHDRAWN_BY_CANDIDATE.value,
}

ORGANIZATION_ACTIVITY_TRANSITIONS: dict[str, tuple[str | None, str | None]] = {
    "team_invitation_created": (None, "pending"),
    "team_invitation_resent": ("pending", "pending"),
    "team_invitation_accepted": ("pending", "accepted"),
    "team_invitation_revoked": ("pending", "revoked"),
    "first_hr_invitation_sent": (None, "pending"),
    "first_hr_invitation_resent": ("pending", "pending"),
}


def _value(value: object | None) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _mask_email(value: str | None) -> str | None:
    if not value:
        return None
    local, separator, domain = value.partition("@")
    if not separator:
        return "Redacted"
    shown = min(2, len(local))
    return f"{local[:shown]}{'*' * max(len(local) - shown, 1)}@{domain}"


def _organization_status(organization: Organization) -> str:
    if organization.suspended_at is not None:
        return "suspended"
    if organization.setup_completed_at is None:
        return "setup_incomplete"
    return "active"


def _status_count(status_counts: dict[str, int], statuses: set[str]) -> int:
    return sum(status_counts.get(status, 0) for status in statuses)


def build_overview_counts(
    *,
    people_count: int,
    status_counts: dict[str, int],
    type_counts: dict[str, int],
) -> AdminOrganizationOverviewResponse:
    total = sum(status_counts.values())
    verified = status_counts.get(VerificationRequestStatus.VERIFIED.value, 0)
    excluded = _status_count(status_counts, EXCLUDED_FROM_COMPLETION_RATE)
    eligible = max(total - excluded, 0)
    return AdminOrganizationOverviewResponse(
        people_count=people_count,
        verification_total=total,
        verified_count=verified,
        pending_count=_status_count(status_counts, PENDING_STATUSES),
        in_progress_count=_status_count(status_counts, IN_PROGRESS_STATUSES),
        needs_attention_count=_status_count(status_counts, NEEDS_ATTENTION_STATUSES),
        cancelled_count=status_counts.get(VerificationRequestStatus.CANCELLED.value, 0),
        withdrawn_count=status_counts.get(
            VerificationRequestStatus.WITHDRAWN_BY_CANDIDATE.value,
            0,
        ),
        completion_rate=round((verified / eligible) * 100, 1) if eligible else None,
        completion_rate_numerator=verified,
        completion_rate_denominator=eligible,
        status_counts=status_counts,
        type_counts=type_counts,
    )


def _date_boundary(value: datetime | date | None, *, end: bool) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.combine(
        value,
        datetime.max.time() if end else datetime.min.time(),
        tzinfo=UTC,
    )


class AdminOrganizationService:
    """Query-efficient Client projections and scoped company-record mutations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._registry_code = TrustRegistryCodeService()

    async def _require_organization(self, public_id: UUID) -> Organization:
        organization = await self._session.scalar(
            select(Organization)
            .options(joinedload(Organization.registry_record))
            .where(Organization.public_id == public_id)
        )
        if organization is None:
            raise NotFoundError("Organization not found")
        return organization

    async def _require_organization_for_update(self, public_id: UUID) -> Organization:
        organization = await self._session.scalar(
            select(Organization)
            .where(Organization.public_id == public_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if organization is None:
            raise NotFoundError("Organization not found")
        return organization

    async def _require_company_record(self, public_id: UUID) -> TrustRegistryRecord:
        record = await self._session.scalar(
            select(TrustRegistryRecord).where(
                TrustRegistryRecord.public_id == public_id,
                TrustRegistryRecord.deleted_at.is_(None),
            )
        )
        if record is None:
            raise NotFoundError("Company record not found")
        if record.lifecycle_status in {"deprecated", "merged"}:
            raise ConflictError("This company record is not available for new connections")
        return record

    async def _primary_domain(self, registry_record_id: UUID) -> str | None:
        return await self._session.scalar(
            select(TrustRegistryDomain.domain)
            .where(
                TrustRegistryDomain.registry_record_id == registry_record_id,
                TrustRegistryDomain.deleted_at.is_(None),
                TrustRegistryDomain.is_primary.is_(True),
            )
            .order_by(TrustRegistryDomain.created_at.asc())
            .limit(1)
        )

    async def _company_record_response(
        self,
        organization: Organization,
        record: TrustRegistryRecord,
        *,
        created: bool,
        already_connected: bool,
        primary_domain: str | None = None,
    ) -> AdminOrganizationCompanyRecordResponse:
        return AdminOrganizationCompanyRecordResponse(
            organization_public_id=organization.public_id,
            registry_record_public_id=record.public_id,
            registry_record_name=record.display_name or record.legal_name,
            registry_record_organization_type=record.organization_type,
            registry_record_primary_domain=(
                primary_domain
                if primary_domain is not None
                else await self._primary_domain(record.id)
            ),
            lifecycle_status=record.lifecycle_status,
            trust_status=record.trust_status,
            created=created,
            already_connected=already_connected,
        )

    async def connect_company_record(
        self,
        actor_user_id: UUID,
        organization_public_id: UUID,
        payload: AdminOrganizationCompanyRecordConnectRequest,
    ) -> AdminOrganizationCompanyRecordResponse:
        organization = await self._require_organization_for_update(organization_public_id)
        record = await self._require_company_record(payload.registry_record_public_id)
        if organization.registry_record_id is not None:
            if organization.registry_record_id != record.id:
                raise ConflictError(
                    "This Client is already connected to a different company record"
                )
            return await self._company_record_response(
                organization,
                record,
                created=False,
                already_connected=True,
            )

        organization.registry_record_id = record.id
        organization.registry_resolution_method = "manual"
        organization.registry_resolution_confidence = Decimal("100")
        organization.registry_resolution_metadata = {
            "source": "admin_client_workspace",
            "idempotency_key": str(payload.idempotency_key),
            "created_company_record": False,
        }
        organization.registry_resolved_at = datetime.now(UTC)
        organization.registry_resolved_by_user_id = actor_user_id
        self._session.add(
            OrganizationActivityEvent(
                organization_id=organization.id,
                actor_user_id=actor_user_id,
                event_type="company_record_connected",
                subject_type="trust_registry_record",
                subject_public_id=str(record.public_id),
                metadata_payload={
                    "company_record_name": record.display_name or record.legal_name,
                    "created_company_record": False,
                },
            )
        )
        await self._session.commit()
        return await self._company_record_response(
            organization,
            record,
            created=False,
            already_connected=False,
        )

    async def create_and_connect_company_record(
        self,
        actor_user_id: UUID,
        organization_public_id: UUID,
        payload: AdminOrganizationCompanyRecordCreateRequest,
    ) -> AdminOrganizationCompanyRecordResponse:
        organization = await self._require_organization_for_update(organization_public_id)
        if organization.registry_record_id is not None:
            record = await self._session.scalar(
                select(TrustRegistryRecord).where(
                    TrustRegistryRecord.id == organization.registry_record_id,
                    TrustRegistryRecord.deleted_at.is_(None),
                )
            )
            if record is None:
                raise ConflictError("The connected company record is unavailable")
            same_request = (organization.registry_resolution_metadata or {}).get(
                "idempotency_key"
            ) == str(payload.idempotency_key)
            if not same_request:
                raise ConflictError("This Client is already connected to a company record")
            return await self._company_record_response(
                organization,
                record,
                created=True,
                already_connected=True,
            )

        public_id = uuid.uuid4()
        record = TrustRegistryRecord(
            public_id=public_id,
            registry_code=self._registry_code.generate(
                public_id=public_id,
                organization_type=payload.organization_type,
            ),
            legal_name=payload.legal_name,
            display_name=payload.display_name,
            organization_type=payload.organization_type,
            country=payload.country,
            state_province=payload.state_province,
            website=payload.website,
            lifecycle_status="draft",
            trust_status="unreviewed",
            registry_confidence_score=Decimal("0"),
            trust_metadata={
                "source": "admin_client_workspace",
                "workspace_public_id": str(organization.public_id),
                "idempotency_key": str(payload.idempotency_key),
            },
            created_by_user_id=actor_user_id,
            updated_by_user_id=actor_user_id,
        )
        self._session.add(record)
        await self._session.flush()
        if payload.primary_domain:
            self._session.add(
                TrustRegistryDomain(
                    registry_record_id=record.id,
                    domain=payload.primary_domain,
                    is_primary=True,
                    is_verified=False,
                    source_type="admin",
                    source_metadata={
                        "source": "admin_client_workspace",
                        "workspace_public_id": str(organization.public_id),
                    },
                )
            )

        organization.registry_record_id = record.id
        organization.registry_resolution_method = "manual"
        organization.registry_resolution_confidence = Decimal("100")
        organization.registry_resolution_metadata = {
            "source": "admin_client_workspace",
            "idempotency_key": str(payload.idempotency_key),
            "created_company_record": True,
        }
        organization.registry_resolved_at = datetime.now(UTC)
        organization.registry_resolved_by_user_id = actor_user_id
        self._session.add(
            OrganizationActivityEvent(
                organization_id=organization.id,
                actor_user_id=actor_user_id,
                event_type="company_record_created_and_connected",
                subject_type="trust_registry_record",
                subject_public_id=str(record.public_id),
                metadata_payload={
                    "company_record_name": record.display_name or record.legal_name,
                    "created_company_record": True,
                    "lifecycle_status": "draft",
                    "trust_status": "unreviewed",
                },
            )
        )
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ConflictError(
                "The company record could not be created safely; retry the search"
            ) from exc
        return await self._company_record_response(
            organization,
            record,
            created=True,
            already_connected=False,
            primary_domain=payload.primary_domain,
        )

    @staticmethod
    def _search_filter(search: str):
        needle = f"%{search.strip()}%"
        return or_(
            Organization.name.ilike(needle),
            func.coalesce(Organization.domain, "").ilike(needle),
            func.coalesce(Organization.website, "").ilike(needle),
            cast(Organization.public_id, String).ilike(needle),
            exists(
                select(1)
                .select_from(OrganizationMember)
                .join(User, User.id == OrganizationMember.user_id)
                .where(
                    OrganizationMember.organization_id == Organization.id,
                    OrganizationMember.role == OrganizationRole.OWNER,
                    User.email.ilike(needle),
                )
            ),
        )

    async def list_organizations(
        self,
        params: AdminOrganizationListParams,
    ) -> AdminOrganizationPage:
        filters = []
        if params.search and params.search.strip():
            filters.append(self._search_filter(params.search))
        if params.organization_type:
            filters.append(cast(Organization.organization_type, String) == params.organization_type)
        if params.status:
            statuses = {part.strip().lower() for part in params.status.split(",") if part.strip()}
            status_filters = []
            if "active" in statuses:
                status_filters.append(
                    and_(
                        Organization.suspended_at.is_(None),
                        Organization.setup_completed_at.is_not(None),
                    )
                )
            if "suspended" in statuses:
                status_filters.append(Organization.suspended_at.is_not(None))
            if "setup_incomplete" in statuses:
                status_filters.append(
                    and_(
                        Organization.suspended_at.is_(None),
                        Organization.setup_completed_at.is_(None),
                    )
                )
            if status_filters:
                filters.append(or_(*status_filters))

        people_stats = (
            select(
                OrganizationPerson.organization_id.label("organization_id"),
                func.count(OrganizationPerson.id).label("people_count"),
            )
            .group_by(OrganizationPerson.organization_id)
            .subquery()
        )
        team_stats = (
            select(
                OrganizationMember.organization_id.label("organization_id"),
                func.count(OrganizationMember.id).label("team_size"),
            )
            .group_by(OrganizationMember.organization_id)
            .subquery()
        )
        request_stats = (
            select(
                VerificationRequest.organization_id.label("organization_id"),
                func.count(VerificationRequest.id).label("request_count"),
                func.count(VerificationRequest.id)
                .filter(VerificationRequest.status == VerificationRequestStatus.VERIFIED)
                .label("verified_count"),
                func.count(VerificationRequest.id)
                .filter(VerificationRequest.status.in_(PENDING_STATUSES))
                .label("pending_count"),
                func.count(VerificationRequest.id)
                .filter(VerificationRequest.status.in_(IN_PROGRESS_STATUSES))
                .label("in_progress_count"),
                func.count(VerificationRequest.id)
                .filter(VerificationRequest.status.in_(NEEDS_ATTENTION_STATUSES))
                .label("needs_attention_count"),
            )
            .where(VerificationRequest.organization_id.is_not(None))
            .group_by(VerificationRequest.organization_id)
            .subquery()
        )

        total = int(
            await self._session.scalar(
                select(func.count()).select_from(Organization).where(*filters)
            )
            or 0
        )
        rows = await self._session.execute(
            select(
                Organization,
                TrustRegistryRecord.public_id.label("registry_record_public_id"),
                func.coalesce(
                    TrustRegistryRecord.display_name,
                    TrustRegistryRecord.legal_name,
                ).label("registry_record_name"),
                func.coalesce(people_stats.c.people_count, 0),
                func.coalesce(team_stats.c.team_size, 0),
                func.coalesce(request_stats.c.request_count, 0),
                func.coalesce(request_stats.c.verified_count, 0),
                func.coalesce(request_stats.c.pending_count, 0),
                func.coalesce(request_stats.c.in_progress_count, 0),
                func.coalesce(request_stats.c.needs_attention_count, 0),
            )
            .outerjoin(
                people_stats,
                people_stats.c.organization_id == Organization.id,
            )
            .outerjoin(team_stats, team_stats.c.organization_id == Organization.id)
            .outerjoin(
                request_stats,
                request_stats.c.organization_id == Organization.id,
            )
            .outerjoin(
                TrustRegistryRecord,
                and_(
                    TrustRegistryRecord.id == Organization.registry_record_id,
                    TrustRegistryRecord.deleted_at.is_(None),
                ),
            )
            .where(*filters)
            .order_by(Organization.name.asc(), Organization.public_id.asc())
            .offset(params.offset or 0)
            .limit(params.limit or 20)
        )
        items = []
        for (
            organization,
            registry_record_public_id,
            registry_record_name,
            people_count,
            team_size,
            request_count,
            verified_count,
            pending_count,
            in_progress_count,
            needs_attention_count,
        ) in rows.all():
            items.append(
                AdminOrganizationListItem(
                    public_id=organization.public_id,
                    name=organization.name,
                    domain=organization.domain,
                    organization_type=_value(organization.organization_type) or "other",
                    registry_record_public_id=registry_record_public_id,
                    registry_record_name=registry_record_name,
                    account_status=_organization_status(organization),
                    verification_state=_value(organization.verification_state) or "unknown",
                    is_workspace_customer=int(team_size) > 0,
                    people_count=int(people_count),
                    request_count=int(request_count),
                    verified_count=int(verified_count),
                    pending_count=int(pending_count),
                    in_progress_count=int(in_progress_count),
                    needs_attention_count=int(needs_attention_count),
                    team_size=int(team_size),
                    updated_at=organization.updated_at,
                )
            )
        return AdminOrganizationPage.create(items=items, total=total, params=params)

    async def get_organization(self, public_id: UUID) -> AdminOrganizationDetailResponse:
        organization = await self._require_organization(public_id)
        owner = (
            await self._session.execute(
                select(OrganizationMember, User)
                .join(User, User.id == OrganizationMember.user_id)
                .where(
                    OrganizationMember.organization_id == organization.id,
                    OrganizationMember.role == OrganizationRole.OWNER,
                )
                .order_by(OrganizationMember.created_at.asc())
                .limit(1)
            )
        ).first()
        team_size = int(
            await self._session.scalar(
                select(func.count())
                .select_from(OrganizationMember)
                .where(OrganizationMember.organization_id == organization.id)
            )
            or 0
        )
        people_count = int(
            await self._session.scalar(
                select(func.count())
                .select_from(OrganizationPerson)
                .where(OrganizationPerson.organization_id == organization.id)
            )
            or 0
        )
        latest_request = await self._session.scalar(
            select(func.max(VerificationRequest.updated_at)).where(
                VerificationRequest.organization_id == organization.id
            )
        )
        latest_person = await self._session.scalar(
            select(func.max(OrganizationPerson.last_activity_at)).where(
                OrganizationPerson.organization_id == organization.id
            )
        )
        owner_user = owner[1] if owner else None
        last_activity = max(
            [
                value
                for value in (organization.updated_at, latest_request, latest_person)
                if value is not None
            ],
            default=None,
        )
        return AdminOrganizationDetailResponse(
            public_id=organization.public_id,
            name=organization.name,
            domain=organization.domain,
            website=organization.website,
            organization_type=_value(organization.organization_type) or "other",
            industry=organization.industry,
            location=organization.location,
            organization_size=organization.organization_size,
            account_status=_organization_status(organization),
            verification_state=_value(organization.verification_state) or "unknown",
            onboarding_status=(
                "completed" if organization.setup_completed_at is not None else "incomplete"
            ),
            is_workspace_customer=team_size > 0,
            primary_owner_name=owner_user.full_name if owner_user else None,
            primary_owner_email_masked=_mask_email(owner_user.email) if owner_user else None,
            team_size=team_size,
            people_count=people_count,
            registry_record_public_id=(
                organization.registry_record.public_id
                if organization.registry_record is not None
                else None
            ),
            registry_record_name=(
                organization.registry_record.display_name or organization.registry_record.legal_name
                if organization.registry_record is not None
                else None
            ),
            registry_record_organization_type=(
                organization.registry_record.organization_type
                if organization.registry_record is not None
                else None
            ),
            registry_record_primary_domain=(
                await self._primary_domain(organization.registry_record.id)
                if organization.registry_record is not None
                else None
            ),
            created_at=organization.created_at,
            updated_at=organization.updated_at,
            last_activity_at=last_activity,
        )

    async def get_overview(self, public_id: UUID) -> AdminOrganizationOverviewResponse:
        organization = await self._require_organization(public_id)
        people_count = int(
            await self._session.scalar(
                select(func.count())
                .select_from(OrganizationPerson)
                .where(OrganizationPerson.organization_id == organization.id)
            )
            or 0
        )
        status_rows = await self._session.execute(
            select(VerificationRequest.status, func.count(VerificationRequest.id))
            .where(VerificationRequest.organization_id == organization.id)
            .group_by(VerificationRequest.status)
        )
        type_rows = await self._session.execute(
            select(VerificationRequest.request_type, func.count(VerificationRequest.id))
            .where(VerificationRequest.organization_id == organization.id)
            .group_by(VerificationRequest.request_type)
        )
        return build_overview_counts(
            people_count=people_count,
            status_counts={
                _value(status) or "unknown": int(count) for status, count in status_rows.all()
            },
            type_counts={
                _value(request_type) or "unknown": int(count)
                for request_type, count in type_rows.all()
            },
        )

    async def list_people(
        self,
        public_id: UUID,
        params: ListQueryParams,
    ) -> AdminOrganizationPeoplePage:
        organization = await self._require_organization(public_id)
        filters = [OrganizationPerson.organization_id == organization.id]
        if params.search and params.search.strip():
            needle = f"%{params.search.strip()}%"
            filters.append(
                or_(
                    OrganizationPerson.full_name.ilike(needle),
                    func.coalesce(OrganizationPerson.primary_email, "").ilike(needle),
                    cast(OrganizationPerson.public_id, String).ilike(needle),
                )
            )
        if params.status:
            statuses = [part.strip() for part in params.status.split(",") if part.strip()]
            if statuses:
                filters.append(OrganizationPerson.lifecycle_status.in_(statuses))

        request_stats = (
            select(
                VerificationRequest.organization_person_id.label("person_id"),
                func.count(VerificationRequest.id).label("request_count"),
                func.count(VerificationRequest.id)
                .filter(VerificationRequest.status == VerificationRequestStatus.VERIFIED)
                .label("verified_count"),
                func.count(VerificationRequest.id)
                .filter(VerificationRequest.status.in_(PENDING_STATUSES | IN_PROGRESS_STATUSES))
                .label("pending_count"),
                func.max(VerificationRequest.updated_at).label("latest_request_at"),
            )
            .where(VerificationRequest.organization_id == organization.id)
            .group_by(VerificationRequest.organization_person_id)
            .subquery()
        )
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(OrganizationPerson).where(*filters)
            )
            or 0
        )
        rows = await self._session.execute(
            select(
                OrganizationPerson,
                func.coalesce(request_stats.c.request_count, 0),
                func.coalesce(request_stats.c.verified_count, 0),
                func.coalesce(request_stats.c.pending_count, 0),
                request_stats.c.latest_request_at,
            )
            .options(selectinload(OrganizationPerson.job_role))
            .outerjoin(request_stats, request_stats.c.person_id == OrganizationPerson.id)
            .where(*filters)
            .order_by(OrganizationPerson.full_name.asc(), OrganizationPerson.public_id.asc())
            .offset(params.offset or 0)
            .limit(params.limit or 20)
        )
        items = []
        for person, request_count, verified_count, pending_count, latest_request_at in rows.all():
            last_activity = max(
                [
                    value
                    for value in (person.last_activity_at, latest_request_at, person.updated_at)
                    if value is not None
                ],
                default=None,
            )
            items.append(
                AdminOrganizationPersonItem(
                    public_id=person.public_id,
                    linked_user_public_id=person.linked_user_id,
                    display_name=person.full_name,
                    email_masked=_mask_email(person.primary_email),
                    relationship=_value(person.relationship) or "unknown",
                    lifecycle_status=_value(person.lifecycle_status) or "unknown",
                    invitation_status=(_value(person.invitation_status_summary) or "not_invited"),
                    role_id=(person.job_role.public_id if person.job_role is not None else None),
                    role_name=(person.job_role.name if person.job_role is not None else None),
                    department=person.department,
                    division=person.division,
                    joining_date=person.joining_date,
                    verification_request_count=int(request_count),
                    verified_count=int(verified_count),
                    pending_count=int(pending_count),
                    last_activity_at=last_activity,
                )
            )
        return AdminOrganizationPeoplePage.create(items=items, total=total, params=params)

    async def list_verifications(
        self,
        public_id: UUID,
        params: AdminOrganizationVerificationListParams,
    ) -> AdminOrganizationVerificationPage:
        organization = await self._require_organization(public_id)
        requester = aliased(User)
        filters = [VerificationRequest.organization_id == organization.id]
        if params.search and params.search.strip():
            needle = f"%{params.search.strip()}%"
            filters.append(
                or_(
                    VerificationRequest.subject_name.ilike(needle),
                    VerificationRequest.subject_email.ilike(needle),
                    cast(VerificationRequest.public_id, String).ilike(needle),
                )
            )
        if params.status:
            statuses = [part.strip() for part in params.status.split(",") if part.strip()]
            if statuses:
                filters.append(VerificationRequest.status.in_(statuses))
        if params.verification_type:
            filters.append(
                cast(VerificationRequest.request_type, String) == params.verification_type
            )
        created_after = _date_boundary(params.created_after, end=False)
        if created_after is not None:
            filters.append(VerificationRequest.created_at >= created_after)
        created_before = _date_boundary(params.created_before, end=True)
        if created_before is not None:
            filters.append(VerificationRequest.created_at <= created_before)

        total = int(
            await self._session.scalar(
                select(func.count()).select_from(VerificationRequest).where(*filters)
            )
            or 0
        )
        rows = await self._session.execute(
            select(
                VerificationRequest,
                OrganizationPerson.public_id,
                requester.full_name,
                requester.email,
            )
            .outerjoin(
                OrganizationPerson,
                OrganizationPerson.id == VerificationRequest.organization_person_id,
            )
            .outerjoin(requester, requester.id == VerificationRequest.requested_by_user_id)
            .where(*filters)
            .order_by(VerificationRequest.created_at.desc(), VerificationRequest.public_id.asc())
            .offset(params.offset or 0)
            .limit(params.limit or 20)
        )
        terminal = {
            VerificationRequestStatus.VERIFIED.value,
            VerificationRequestStatus.REJECTED.value,
            VerificationRequestStatus.UNABLE_TO_VERIFY.value,
            VerificationRequestStatus.CANCELLED.value,
            VerificationRequestStatus.WITHDRAWN_BY_CANDIDATE.value,
            VerificationRequestStatus.EXPIRED.value,
        }
        items = []
        for request, person_public_id, requester_name, requester_email in rows.all():
            status = _value(request.status) or "unknown"
            items.append(
                AdminOrganizationVerificationItem(
                    public_id=request.public_id,
                    organization_person_public_id=person_public_id,
                    candidate_name=request.subject_name,
                    candidate_email_masked=_mask_email(request.subject_email) or "Redacted",
                    request_type=_value(request.request_type) or "unknown",
                    requested_by=requester_name or _mask_email(requester_email),
                    created_at=request.created_at,
                    status=status,
                    completed_at=request.updated_at if status in terminal else None,
                    updated_at=request.updated_at,
                )
            )
        return AdminOrganizationVerificationPage.create(
            items=items,
            total=total,
            params=params,
        )

    async def list_team(
        self,
        public_id: UUID,
        params: ListQueryParams,
    ) -> AdminOrganizationTeamPage:
        organization = await self._require_organization(public_id)
        filters = [OrganizationMember.organization_id == organization.id]
        if params.search and params.search.strip():
            needle = f"%{params.search.strip()}%"
            filters.append(or_(User.full_name.ilike(needle), User.email.ilike(needle)))
        if params.status:
            statuses = {part.strip().lower() for part in params.status.split(",") if part.strip()}
            status_filters = []
            if "active" in statuses:
                status_filters.append(
                    and_(OrganizationMember.suspended_at.is_(None), User.is_active.is_(True))
                )
            if "suspended" in statuses:
                status_filters.append(
                    or_(OrganizationMember.suspended_at.is_not(None), User.is_active.is_(False))
                )
            if status_filters:
                filters.append(or_(*status_filters))

        activity = (
            select(
                RefreshToken.user_id.label("user_id"),
                func.max(RefreshToken.updated_at).label("last_activity_at"),
            )
            .group_by(RefreshToken.user_id)
            .subquery()
        )
        total = int(
            await self._session.scalar(
                select(func.count())
                .select_from(OrganizationMember)
                .join(User, User.id == OrganizationMember.user_id)
                .where(*filters)
            )
            or 0
        )
        rows = await self._session.execute(
            select(OrganizationMember, User, activity.c.last_activity_at)
            .join(User, User.id == OrganizationMember.user_id)
            .outerjoin(activity, activity.c.user_id == User.id)
            .where(*filters)
            .order_by(OrganizationMember.created_at.asc(), OrganizationMember.public_id.asc())
            .offset(params.offset or 0)
            .limit(params.limit or 20)
        )
        items = [
            AdminOrganizationTeamItem(
                public_id=membership.public_id,
                user_public_id=user.id,
                display_name=user.full_name or "Unnamed workspace user",
                email_masked=_mask_email(user.email) or "Redacted",
                role=_value(membership.role) or "member",
                status=(
                    "suspended"
                    if membership.suspended_at is not None or not user.is_active
                    else "active"
                ),
                joined_at=membership.created_at,
                last_activity_at=last_activity_at,
            )
            for membership, user, last_activity_at in rows.all()
        ]
        return AdminOrganizationTeamPage.create(items=items, total=total, params=params)

    async def list_activity(
        self,
        public_id: UUID,
        params: ListQueryParams,
    ) -> AdminOrganizationActivityPage:
        organization = await self._require_organization(public_id)
        verification_actor = aliased(User)
        invitation_actor = aliased(User)
        organization_actor = aliased(User)
        verification_events = (
            select(
                VerificationRequestEvent.id.label("public_id"),
                VerificationRequestEvent.created_at.label("occurred_at"),
                VerificationRequestEvent.event_type.label("event_type"),
                literal("verification_request").label("source"),
                verification_actor.full_name.label("actor_name"),
                verification_actor.role.label("actor_role"),
                verification_actor.email.label("actor_email"),
                cast(VerificationRequest.public_id, String).label("subject_public_id"),
                cast(VerificationRequestEvent.previous_status, String).label("previous_status"),
                cast(VerificationRequestEvent.new_status, String).label("new_status"),
                literal(organization.name).label("organization_name"),
                literal(None, type_=String).label("on_behalf_of_organization_name"),
            )
            .join(
                VerificationRequest,
                VerificationRequest.id == VerificationRequestEvent.verification_request_id,
            )
            .outerjoin(
                verification_actor,
                verification_actor.id == VerificationRequestEvent.actor_user_id,
            )
            .where(VerificationRequest.organization_id == organization.id)
        )
        invitation_events = (
            select(
                TrustInvitationEvent.id.label("public_id"),
                TrustInvitationEvent.occurred_at.label("occurred_at"),
                TrustInvitationEvent.event_type.label("event_type"),
                literal("trust_invitation").label("source"),
                invitation_actor.full_name.label("actor_name"),
                invitation_actor.role.label("actor_role"),
                invitation_actor.email.label("actor_email"),
                cast(TrustInvitation.public_id, String).label("subject_public_id"),
                literal(None, type_=String).label("previous_status"),
                literal(None, type_=String).label("new_status"),
                literal(organization.name).label("organization_name"),
                literal(None, type_=String).label("on_behalf_of_organization_name"),
            )
            .join(
                TrustInvitation,
                TrustInvitation.id == TrustInvitationEvent.invitation_id,
            )
            .outerjoin(
                invitation_actor,
                invitation_actor.id == TrustInvitationEvent.actor_user_id,
            )
            .where(TrustInvitation.organization_id == organization.id)
        )
        organization_events = (
            select(
                OrganizationActivityEvent.public_id.label("public_id"),
                OrganizationActivityEvent.created_at.label("occurred_at"),
                OrganizationActivityEvent.event_type.label("event_type"),
                literal("organization_activity").label("source"),
                organization_actor.full_name.label("actor_name"),
                organization_actor.role.label("actor_role"),
                organization_actor.email.label("actor_email"),
                OrganizationActivityEvent.subject_public_id.label("subject_public_id"),
                literal(None, type_=String).label("previous_status"),
                literal(None, type_=String).label("new_status"),
                literal(organization.name).label("organization_name"),
                literal(organization.name).label("on_behalf_of_organization_name"),
            )
            .outerjoin(
                organization_actor,
                organization_actor.id == OrganizationActivityEvent.actor_user_id,
            )
            .where(OrganizationActivityEvent.organization_id == organization.id)
        )
        combined = union_all(
            verification_events,
            invitation_events,
            organization_events,
        ).subquery()
        total = int(await self._session.scalar(select(func.count()).select_from(combined)) or 0)
        rows = await self._session.execute(
            select(combined)
            .order_by(combined.c.occurred_at.desc(), combined.c.public_id.asc())
            .offset(params.offset or 0)
            .limit(params.limit or 20)
        )
        items = [
            AdminOrganizationActivityItem(
                public_id=row.public_id,
                occurred_at=row.occurred_at,
                event_type=row.event_type,
                source=row.source,
                actor_name=row.actor_name or _mask_email(row.actor_email),
                actor_role=row.actor_role,
                actor_email_masked=_mask_email(row.actor_email),
                organization_name=row.organization_name,
                on_behalf_of_organization_name=row.on_behalf_of_organization_name,
                subject_public_id=row.subject_public_id,
                previous_status=(
                    ORGANIZATION_ACTIVITY_TRANSITIONS.get(row.event_type, (None, None))[0]
                    if row.source == "organization_activity"
                    else row.previous_status
                ),
                new_status=(
                    ORGANIZATION_ACTIVITY_TRANSITIONS.get(row.event_type, (None, None))[1]
                    if row.source == "organization_activity"
                    else row.new_status
                ),
            )
            for row in rows
        ]
        return AdminOrganizationActivityPage.create(items=items, total=total, params=params)
