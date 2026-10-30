"""Trust invitation engine use cases."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import hash_refresh_token
from app.config import Settings
from app.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.models.certification import Certification
from app.models.digilocker_identity_verification import DigiLockerIdentityVerification
from app.models.education import Education
from app.models.employment import Employment
from app.models.employment_reference import EmploymentReference
from app.models.organization_job_role import OrganizationJobRole
from app.models.passport_share_link import PassportShareLink
from app.models.permanent_address import PermanentAddressVersion
from app.models.trust_invitation import TrustInvitation
from app.models.trust_invitation_event import TrustInvitationEvent
from app.models.user import User
from app.notifications.contracts import NotificationRequest
from app.organization.permissions import is_organization_manager
from app.repositories.trust_invitation import TrustInvitationRepository
from app.repositories.user import UserRepository
from app.schemas.hr_v2 import DEFAULT_VERIFICATION_PREFERENCES
from app.schemas.pagination import ListQueryParams, Page, filter_sort_paginate
from app.schemas.trust_invitation import (
    CandidateInvitationHomeSummary,
    CandidateTrustInvitationResponse,
    TrustInvitationAcceptResponse,
    TrustInvitationCreateRequest,
    TrustInvitationCreateResponse,
    TrustInvitationDetailResponse,
    TrustInvitationDraftUpdateRequest,
    TrustInvitationFinalizeRequest,
    TrustInvitationPublicLookupResponse,
    TrustInvitationRequirementProgress,
    TrustInvitationResponse,
    TrustInvitationSummaryResponse,
    TrustInvitationTimelineEventResponse,
)
from app.services.notification_service import NotificationService
from app.services.organization_person_service import OrganizationPersonService
from app.services.organization_service import OrganizationService
from app.trust_invitations.enums import (
    TrustInvitationDeliveryState,
    TrustInvitationEventType,
    TrustInvitationStatus,
    TrustInvitationVerificationType,
)

logger = logging.getLogger(__name__)


def _public_subject_email(email: str | None) -> str | None:
    """Hide Candidate deletion tombstones from Trust Invitation projections."""
    if email and email.endswith("@deleted.kairoid.invalid"):
        return None
    return email


class TrustInvitationService:
    """Organization-issued trust invitations with public token resolution."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        repo: TrustInvitationRepository | None = None,
        organizations: OrganizationService | None = None,
        notifications: NotificationService | None = None,
        people: OrganizationPersonService | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._repo = repo or TrustInvitationRepository(session)
        self._organizations = organizations or OrganizationService(session)
        self._notifications = notifications or NotificationService(session, settings)
        self._people = people or OrganizationPersonService(session, settings)

    async def create(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        payload: TrustInvitationCreateRequest,
    ) -> TrustInvitationCreateResponse:
        organization, _ = await self._organizations.require_org_member(actor_user_id, org_public_id)
        job_role = None
        if payload.role_id is not None:
            job_role = (
                await self._session.execute(
                    select(OrganizationJobRole).where(
                        OrganizationJobRole.organization_id == organization.id,
                        OrganizationJobRole.public_id == payload.role_id,
                    )
                )
            ).scalar_one_or_none()
            if job_role is None:
                raise NotFoundError("Organization job role not found")
            if not job_role.is_active:
                raise ConflictError("Inactive job roles cannot be assigned to invitations")
        preferences = self._preference_snapshot(
            getattr(organization, "verification_preferences", None)
        )
        requested_types = list(payload.requested_verification_types)
        uses_defaults = "requested_verification_types" not in payload.model_fields_set
        if uses_defaults:
            requested_types = self._verification_types_from_preferences(preferences)
        preferences["requested_types_source"] = "defaults" if uses_defaults else "explicit"
        preferences["reference_count_applied"] = False
        requirements_snapshot = self._requirements_snapshot(payload.requirements, requested_types)
        requested_types = [
            TrustInvitationVerificationType(item["type"]) for item in requirements_snapshot
        ]
        if (
            TrustInvitationVerificationType.PROFESSIONAL_REFERENCE in requested_types
            and preferences["reference_count"] > 0
        ):
            raise ValidationAppError(
                "Reference-count orchestration is not supported; set reference_count to 0. "
                "References use the existing per-employment nomination workflow."
            )
        invitation_public_id = secrets.token_hex(16)
        invitation_uuid = UUID(hex=invitation_public_id)
        signed_token = self._build_signed_token(invitation_uuid)
        invitation = TrustInvitation(
            public_id=invitation_uuid,
            organization_id=organization.id,
            subject_name=payload.subject_name,
            subject_email=self._normalize_email(str(payload.subject_email)),
            subject_phone=payload.subject_phone,
            purpose=payload.purpose or (job_role.name if job_role is not None else None),
            role_id=job_role.id if job_role is not None else None,
            requested_verification_types=[item.value for item in requested_types],
            verification_preferences_snapshot=preferences,
            requirements_snapshot=requirements_snapshot,
            requirements_version=1,
            message=payload.message,
            token_hash=hash_refresh_token(signed_token),
            status=(
                TrustInvitationStatus.DRAFT
                if payload.mode == "draft"
                else TrustInvitationStatus.PENDING
            ),
            delivery_method=payload.delivery_method,
            delivery_state=TrustInvitationDeliveryState.QUEUED,
            created_by_user_id=actor_user_id,
            expires_at=payload.expires_at,
            sent_at=None,
            candidate_state=("available" if payload.mode == "send" else None),
        )
        await self._repo.create(invitation)
        await self._record_event(
            invitation,
            TrustInvitationEventType.CREATED,
            actor_user_id=actor_user_id,
        )
        await self._session.commit()

        refreshed = await self._repo.get_by_public_id(invitation.public_id, include_events=True)
        if refreshed is None:
            raise NotFoundError("Trust invitation not found")
        await self._sync_person_link_best_effort(
            refreshed.public_id,
            actor_user_id=actor_user_id,
        )
        refreshed = await self._repo.get_by_public_id(invitation.public_id, include_events=True)
        if refreshed is None:
            raise NotFoundError("Trust invitation not found")

        if payload.mode == "send":
            await self._deliver_invitation(
                refreshed,
                actor_user_id=actor_user_id,
                trigger_event=TrustInvitationEventType.SENT,
                record_event=False,
            )
            await self._session.commit()
            refreshed = await self._repo.get_by_public_id(invitation.public_id, include_events=True)
            if refreshed is None:
                raise NotFoundError("Trust invitation not found")

        return TrustInvitationCreateResponse(
            **(await self._to_response_with_progress(refreshed)).model_dump(),
            invitation_url=self._build_invitation_url(refreshed.public_id),
        )

    async def update_draft(
        self,
        actor_user_id: UUID,
        invitation_public_id: UUID,
        payload: TrustInvitationDraftUpdateRequest,
    ) -> TrustInvitationDetailResponse:
        invitation = await self._require_member_visible_invitation(
            actor_user_id, invitation_public_id, include_events=True
        )
        if invitation.status != TrustInvitationStatus.DRAFT:
            raise ConflictError("Only draft trust invitations can be edited")
        if payload.role_id is not None:
            role = (
                await self._session.execute(
                    select(OrganizationJobRole).where(
                        OrganizationJobRole.organization_id == invitation.organization_id,
                        OrganizationJobRole.public_id == payload.role_id,
                        OrganizationJobRole.status == "active",
                    )
                )
            ).scalar_one_or_none()
            if role is None:
                raise NotFoundError("Active Hiring Role not found")
            invitation.role_id = role.id
        elif "role_id" in payload.model_fields_set:
            invitation.role_id = None
        for field in ("subject_name", "subject_phone", "purpose", "message", "expires_at"):
            if field in payload.model_fields_set:
                setattr(invitation, field, getattr(payload, field))
        if payload.subject_email is not None:
            invitation.subject_email = self._normalize_email(str(payload.subject_email))
        if payload.requirements is not None:
            invitation.requirements_snapshot = self._requirements_snapshot(payload.requirements, [])
            invitation.requested_verification_types = [
                item["type"] for item in invitation.requirements_snapshot
            ]
            invitation.requirements_version += 1
        await self._record_event(
            invitation, TrustInvitationEventType.UPDATED, actor_user_id=actor_user_id
        )
        await self._session.commit()
        refreshed = await self._repo.get_by_public_id(invitation_public_id, include_events=True)
        if refreshed is None:
            raise NotFoundError("Trust invitation not found")
        return await self._to_detail_response_with_progress(refreshed)

    async def list_my(self, actor_user_id: UUID) -> list[CandidateTrustInvitationResponse]:
        user = await UserRepository(self._session).get_by_id(actor_user_id)
        if user is not None and user.email_verified_at is None:
            raise ForbiddenError("Verify your email before accepting Trust Invitations")
        invitations = await self._repo.list_for_verified_email(self._normalize_email(user.email))
        changed = await self._expire_many(invitations)
        if changed:
            await self._session.commit()
        return [
            await self._to_candidate_response(invitation, user)
            for invitation in invitations
            if invitation.status != TrustInvitationStatus.DRAFT
        ]

    async def get_my(
        self, actor_user_id: UUID, invitation_public_id: UUID
    ) -> CandidateTrustInvitationResponse:
        user, invitation = await self._require_candidate_invitation(
            actor_user_id, invitation_public_id
        )
        return await self._to_candidate_response(invitation, user)

    async def accept_my(
        self, actor_user_id: UUID, invitation_public_id: UUID
    ) -> CandidateTrustInvitationResponse:
        user, invitation = await self._require_candidate_invitation(
            actor_user_id, invitation_public_id
        )
        if invitation.status in {
            TrustInvitationStatus.CANCELLED,
            TrustInvitationStatus.EXPIRED,
        }:
            raise ConflictError("This invitation is no longer actionable")
        if invitation.declined_at is not None:
            raise ConflictError("Declined invitations are no longer actionable")
        if invitation.accepted_by_user_id not in {None, user.id}:
            raise ForbiddenError(
                "This trust invitation is not assigned to the authenticated account"
            )
        if invitation.accepted_at is None:
            now = datetime.now(tz=UTC)
            invitation.status = TrustInvitationStatus.ACCEPTED
            invitation.accepted_by_user_id = user.id
            invitation.accepted_at = now
            invitation.claimed_at = now
            invitation.candidate_state = "accepted"
            await self._record_event(
                invitation, TrustInvitationEventType.ACCEPTED, actor_user_id=user.id
            )
            await self._session.commit()
            await self._sync_person_link_best_effort(invitation.public_id, actor_user_id=user.id)
            await self._notify_hr_lifecycle(invitation, "trust_invitation_accepted", user.id)
            invitation = await self._repo.get_by_public_id(invitation.public_id) or invitation
        return await self._to_candidate_response(invitation, user)

    async def decline_my(
        self, actor_user_id: UUID, invitation_public_id: UUID
    ) -> CandidateTrustInvitationResponse:
        user, invitation = await self._require_candidate_invitation(
            actor_user_id, invitation_public_id
        )
        if invitation.status in {
            TrustInvitationStatus.CANCELLED,
            TrustInvitationStatus.EXPIRED,
        }:
            raise ConflictError("This invitation is no longer actionable")
        if invitation.completed_at is not None:
            raise ConflictError("Completed invitations cannot be declined")
        if invitation.declined_at is None:
            invitation.declined_at = datetime.now(tz=UTC)
            invitation.candidate_state = "declined"
            await self._record_event(
                invitation, TrustInvitationEventType.DECLINED, actor_user_id=user.id
            )
            await self._session.commit()
        return await self._to_candidate_response(invitation, user)

    async def finalize_my(
        self,
        actor_user_id: UUID,
        invitation_public_id: UUID,
        payload: TrustInvitationFinalizeRequest,
    ) -> CandidateTrustInvitationResponse:
        user, invitation = await self._require_candidate_invitation(
            actor_user_id, invitation_public_id
        )
        if invitation.accepted_at is None or invitation.declined_at is not None:
            raise ConflictError("Accept the invitation before sharing a Passport")
        if payload.consent_version != invitation.requirements_version:
            raise ConflictError("Invitation requirements changed; review and consent again")
        progress = await self._requirement_progress(invitation, user)
        if any(item.mandatory and item.status != "completed" for item in progress):
            raise ConflictError("Complete all mandatory invitation requirements first")
        share = (
            await self._session.execute(
                select(PassportShareLink).where(
                    PassportShareLink.id == payload.passport_share_id,
                    PassportShareLink.owner_user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if (
            share is None
            or share.revoked_at is not None
            or (share.expires_at is not None and share.expires_at <= datetime.now(tz=UTC))
        ):
            raise NotFoundError("Active Passport share not found")
        self._assert_share_scope(invitation, share)
        now = datetime.now(tz=UTC)
        invitation.passport_share_link_id = share.id
        invitation.consented_at = now
        invitation.consent_version = payload.consent_version
        invitation.completed_at = now
        invitation.candidate_state = "completed"
        await self._record_event(
            invitation,
            TrustInvitationEventType.COMPLETED,
            actor_user_id=user.id,
            metadata={"requirements_version": payload.consent_version},
        )
        await self._session.commit()
        await self._notify_hr_lifecycle(invitation, "trust_invitation_completed", user.id)
        return await self._to_candidate_response(invitation, user)

    async def home_summary(self, actor_user_id: UUID) -> CandidateInvitationHomeSummary:
        items = await self.list_my(actor_user_id)
        actionable = [
            item
            for item in items
            if item.lifecycle_state not in {"completed", "declined", "expired", "cancelled"}
        ]
        needs_action = [
            item
            for item in actionable
            if any(req.status != "completed" for req in item.requirements)
        ]
        return CandidateInvitationHomeSummary(
            pending_invitation_count=len(actionable),
            action_required_invitation_count=len(needs_action),
            latest_actionable_invitation=actionable[0] if actionable else None,
        )

    async def get_detail(
        self,
        actor_user_id: UUID,
        invitation_public_id: UUID,
    ) -> TrustInvitationDetailResponse:
        invitation = await self._require_member_visible_invitation(
            actor_user_id,
            invitation_public_id,
            include_events=True,
        )
        changed = await self._expire_if_needed(invitation)
        if changed:
            await self._session.commit()
            invitation = await self._repo.get_by_public_id(
                invitation_public_id,
                include_events=True,
            )
            if invitation is None:
                raise NotFoundError("Trust invitation not found")
        return await self._to_detail_response_with_progress(invitation)

    async def get_summary(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
    ) -> TrustInvitationSummaryResponse:
        organization, _ = await self._organizations.require_org_member(actor_user_id, org_public_id)
        invitations = await self._repo.list_for_organization(organization.id)
        changed = await self._expire_many(invitations)
        if changed:
            await self._session.commit()
            invitations = await self._repo.list_for_organization(organization.id)

        now = datetime.now(tz=UTC)
        expiring_cutoff = now + timedelta(days=2)
        return TrustInvitationSummaryResponse(
            active_count=sum(
                1
                for invitation in invitations
                if invitation.status == TrustInvitationStatus.PENDING
                and getattr(invitation, "declined_at", None) is None
            ),
            accepted_count=sum(
                1
                for invitation in invitations
                if invitation.status == TrustInvitationStatus.ACCEPTED
            ),
            cancelled_count=sum(
                1
                for invitation in invitations
                if invitation.status == TrustInvitationStatus.CANCELLED
            ),
            expiring_soon_count=sum(
                1
                for invitation in invitations
                if invitation.status == TrustInvitationStatus.PENDING
                and invitation.expires_at <= expiring_cutoff
            ),
            draft_count=sum(
                1 for invitation in invitations if invitation.status == TrustInvitationStatus.DRAFT
            ),
        )

    async def list_for_organization(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        params: ListQueryParams | None = None,
    ) -> list[TrustInvitationResponse] | Page[TrustInvitationResponse]:
        organization, _ = await self._organizations.require_org_member(actor_user_id, org_public_id)
        invitations = await self._repo.list_for_organization(organization.id)
        changed = await self._expire_many(invitations)
        if changed:
            await self._session.commit()
            invitations = await self._repo.list_for_organization(organization.id)
        responses = [
            await self._to_response_with_progress(invitation) for invitation in invitations
        ]
        if params is None:
            return responses
        return filter_sort_paginate(
            responses,
            params=params,
            search_fields=("subject_name", "subject_email", "purpose", "status", "delivery_state"),
            allowed_sort_fields=(
                "created_at",
                "updated_at",
                "expires_at",
                "subject_name",
                "subject_email",
                "purpose",
                "status",
                "delivery_state",
                "sent_at",
                "opened_at",
            ),
            default_sort_by="created_at",
        )

    async def send(
        self,
        actor_user_id: UUID,
        invitation_public_id: UUID,
    ) -> TrustInvitationDetailResponse:
        invitation = await self._require_member_visible_invitation(
            actor_user_id,
            invitation_public_id,
            include_events=True,
        )
        await self._expire_or_raise_non_actionable(invitation)
        if invitation.status != TrustInvitationStatus.DRAFT:
            raise ConflictError("Only draft trust invitations can be sent")

        invitation.status = TrustInvitationStatus.PENDING
        await self._deliver_invitation(
            invitation,
            actor_user_id=actor_user_id,
            trigger_event=TrustInvitationEventType.SENT,
            record_event=False,
        )
        await self._session.commit()

        refreshed = await self._repo.get_by_public_id(invitation_public_id, include_events=True)
        if refreshed is None:
            raise NotFoundError("Trust invitation not found")
        return await self._to_detail_response_with_progress(refreshed)

    async def resend(
        self,
        actor_user_id: UUID,
        invitation_public_id: UUID,
    ) -> TrustInvitationDetailResponse:
        invitation = await self._require_member_visible_invitation(
            actor_user_id,
            invitation_public_id,
            include_events=True,
        )
        await self._expire_or_raise_non_actionable(invitation)
        if invitation.status == TrustInvitationStatus.DRAFT:
            raise ConflictError("Draft trust invitations must be sent before they can be resent")

        await self._record_event(
            invitation,
            TrustInvitationEventType.RESENT,
            actor_user_id=actor_user_id,
        )
        await self._deliver_invitation(
            invitation,
            actor_user_id=actor_user_id,
            trigger_event=TrustInvitationEventType.RESENT,
            record_event=False,
        )
        await self._session.commit()

        refreshed = await self._repo.get_by_public_id(invitation_public_id, include_events=True)
        if refreshed is None:
            raise NotFoundError("Trust invitation not found")
        return await self._to_detail_response_with_progress(refreshed)

    async def delete(self, actor_user_id: UUID, invitation_public_id: UUID) -> None:
        invitation = await self._require_member_visible_invitation(
            actor_user_id,
            invitation_public_id,
        )
        if invitation.status != TrustInvitationStatus.DRAFT:
            raise ConflictError("Only draft trust invitations can be deleted")
        await self._repo.delete(invitation)
        await self._session.commit()

    async def get_public_by_token(self, raw_token: str) -> TrustInvitationPublicLookupResponse:
        invitation = await self._resolve_active_token(raw_token)
        changed = False
        if invitation.opened_at is None:
            invitation.opened_at = datetime.now(tz=UTC)
            await self._record_event(invitation, TrustInvitationEventType.OPENED)
            changed = True
        if changed:
            await self._session.commit()
            invitation = await self._repo.get_by_public_id(invitation.public_id)
            if invitation is None:
                raise NotFoundError("Trust invitation not found")
        job_role = getattr(invitation, "job_role", None)
        return TrustInvitationPublicLookupResponse(
            public_id=invitation.public_id,
            organization_name=invitation.organization.name,
            subject_name=invitation.subject_name,
            purpose=invitation.purpose,
            role_id=job_role.public_id if job_role is not None else None,
            role=job_role.name if job_role is not None else None,
            requested_verification_types=self._deserialize_verification_types(
                invitation.requested_verification_types
            ),
            expires_at=invitation.expires_at,
            status=invitation.status,
        )

    async def accept(
        self,
        raw_token: str,
        actor_user_id: UUID,
        actor_email: str,
    ) -> TrustInvitationAcceptResponse:
        user = await UserRepository(self._session).get_by_id(actor_user_id)
        if user is not None and user.email_verified_at is None:
            raise ForbiddenError("Verify your email before accepting Trust Invitations")
        invitation = await self._resolve_token_for_accept(raw_token)
        if self._normalize_email(actor_email) != invitation.subject_email:
            raise ForbiddenError(
                "This trust invitation is not assigned to the authenticated account"
            )

        invitation_public_id = invitation.public_id
        if (
            invitation.status == TrustInvitationStatus.ACCEPTED
            and invitation.accepted_at is not None
        ):
            if (
                invitation.accepted_by_user_id is not None
                and invitation.accepted_by_user_id != actor_user_id
            ):
                raise ForbiddenError(
                    "This trust invitation is not assigned to the authenticated account"
                )
            await self._sync_person_link_best_effort(
                invitation_public_id,
                actor_user_id=invitation.accepted_by_user_id or actor_user_id,
            )
            refreshed = await self._repo.get_by_public_id(invitation_public_id)
            if refreshed is None or refreshed.accepted_at is None:
                raise NotFoundError("Trust invitation not found")
            return TrustInvitationAcceptResponse(
                public_id=refreshed.public_id,
                organization_public_id=refreshed.organization.public_id,
                status=refreshed.status,
                accepted_at=refreshed.accepted_at,
            )

        now = datetime.now(tz=UTC)
        if invitation.opened_at is None:
            invitation.opened_at = now
            await self._record_event(
                invitation,
                TrustInvitationEventType.OPENED,
                actor_user_id=actor_user_id,
            )

        invitation.status = TrustInvitationStatus.ACCEPTED
        invitation.accepted_by_user_id = actor_user_id
        invitation.accepted_at = now
        invitation.claimed_at = now
        invitation.candidate_state = "accepted"
        await self._record_event(
            invitation,
            TrustInvitationEventType.ACCEPTED,
            actor_user_id=actor_user_id,
        )
        await self._session.commit()
        await self._sync_person_link_best_effort(
            invitation_public_id,
            actor_user_id=actor_user_id,
        )
        await self._notify_hr_lifecycle(invitation, "trust_invitation_accepted", actor_user_id)

        refreshed = await self._repo.get_by_public_id(invitation_public_id)
        if refreshed is None or refreshed.accepted_at is None:
            raise NotFoundError("Trust invitation not found")
        return TrustInvitationAcceptResponse(
            public_id=refreshed.public_id,
            organization_public_id=refreshed.organization.public_id,
            status=refreshed.status,
            accepted_at=refreshed.accepted_at,
        )

    async def cancel(
        self,
        actor_user_id: UUID,
        invitation_public_id: UUID,
    ) -> TrustInvitationResponse:
        invitation = await self._require_member_visible_invitation(
            actor_user_id,
            invitation_public_id,
        )
        _, actor_membership = await self._organizations.require_org_member(
            actor_user_id,
            invitation.organization.public_id,
        )
        if not is_organization_manager(actor_membership.role):
            raise ForbiddenError("Only organization owners or admins can cancel trust invitations")

        await self._expire_or_raise_non_actionable(invitation)
        if invitation.status == TrustInvitationStatus.ACCEPTED:
            raise ConflictError("Accepted trust invitations cannot be cancelled")
        if invitation.status == TrustInvitationStatus.CANCELLED:
            return self._to_response(invitation)

        invitation.status = TrustInvitationStatus.CANCELLED
        invitation.cancelled_at = datetime.now(tz=UTC)
        await self._record_event(
            invitation,
            TrustInvitationEventType.CANCELLED,
            actor_user_id=actor_user_id,
        )
        await self._session.commit()

        refreshed = await self._repo.get_by_public_id(invitation.public_id)
        if refreshed is None:
            raise NotFoundError("Trust invitation not found")
        return self._to_response(refreshed)

    async def _require_member_visible_invitation(
        self,
        actor_user_id: UUID,
        invitation_public_id: UUID,
        *,
        include_events: bool = False,
    ) -> TrustInvitation:
        invitation = await self._repo.get_by_public_id(
            invitation_public_id,
            include_events=include_events,
        )
        if invitation is None:
            raise NotFoundError("Trust invitation not found")
        await self._organizations.require_org_member(
            actor_user_id,
            invitation.organization.public_id,
        )
        return invitation

    async def _resolve_active_token(self, raw_token: str) -> TrustInvitation:
        from app.services.organization_lifecycle import require_organization_open

        if not raw_token or len(raw_token) < 16:
            raise NotFoundError("Trust invitation not found")

        invitation: TrustInvitation | None
        signed_public_id = self._verify_signed_token(raw_token)
        if signed_public_id is not None:
            invitation = await self._repo.get_by_public_id(signed_public_id)
        else:
            invitation = await self._repo.get_by_token_hash(hash_refresh_token(raw_token))

        if invitation is None:
            raise NotFoundError("Trust invitation not found")

        await require_organization_open(self._session, invitation.organization_id)
        expired = await self._expire_if_needed(invitation)
        if expired:
            await self._session.commit()
            raise NotFoundError("Trust invitation not found")

        if invitation.status not in {TrustInvitationStatus.DRAFT, TrustInvitationStatus.PENDING}:
            raise NotFoundError("Trust invitation not found")
        if invitation.cancelled_at is not None or invitation.accepted_at is not None:
            raise NotFoundError("Trust invitation not found")
        return invitation

    async def _resolve_token_for_accept(self, raw_token: str) -> TrustInvitation:
        from app.services.organization_lifecycle import require_organization_open

        if not raw_token or len(raw_token) < 16:
            raise NotFoundError("Trust invitation not found")

        invitation: TrustInvitation | None
        signed_public_id = self._verify_signed_token(raw_token)
        if signed_public_id is not None:
            invitation = await self._repo.get_by_public_id(signed_public_id)
        else:
            invitation = await self._repo.get_by_token_hash(hash_refresh_token(raw_token))

        if invitation is None:
            raise NotFoundError("Trust invitation not found")

        await require_organization_open(self._session, invitation.organization_id)
        expired = await self._expire_if_needed(invitation)
        if expired:
            await self._session.commit()
            raise NotFoundError("Trust invitation not found")

        if (
            invitation.status == TrustInvitationStatus.ACCEPTED
            and invitation.accepted_at is not None
        ):
            return invitation
        if invitation.status not in {TrustInvitationStatus.DRAFT, TrustInvitationStatus.PENDING}:
            raise NotFoundError("Trust invitation not found")
        if invitation.cancelled_at is not None or invitation.accepted_at is not None:
            raise NotFoundError("Trust invitation not found")
        return invitation

    async def _expire_or_raise_non_actionable(self, invitation: TrustInvitation) -> None:
        expired = await self._expire_if_needed(invitation)
        if expired or invitation.status == TrustInvitationStatus.EXPIRED:
            await self._session.commit()
            raise ConflictError("Expired trust invitations are no longer actionable")
        if invitation.status == TrustInvitationStatus.CANCELLED:
            raise ConflictError("Cancelled trust invitations are no longer actionable")
        if getattr(invitation, "declined_at", None) is not None:
            raise ConflictError("Declined trust invitations are no longer actionable")
        if getattr(invitation, "completed_at", None) is not None:
            raise ConflictError("Completed trust invitations are no longer actionable")

    async def _expire_many(self, invitations: list[TrustInvitation]) -> bool:
        changed = False
        for invitation in invitations:
            changed = await self._expire_if_needed(invitation) or changed
        return changed

    async def _expire_if_needed(self, invitation: TrustInvitation) -> bool:
        if invitation.status in {
            TrustInvitationStatus.ACCEPTED,
            TrustInvitationStatus.CANCELLED,
            TrustInvitationStatus.EXPIRED,
        }:
            return False
        if getattr(invitation, "declined_at", None) is not None:
            return False
        if invitation.expires_at > datetime.now(tz=UTC):
            return False

        invitation.status = TrustInvitationStatus.EXPIRED
        await self._record_event(invitation, TrustInvitationEventType.EXPIRED)
        return True

    async def _deliver_invitation(
        self,
        invitation: TrustInvitation,
        *,
        actor_user_id: UUID | None,
        trigger_event: TrustInvitationEventType,
        record_event: bool,
    ) -> None:
        if record_event:
            await self._record_event(invitation, trigger_event, actor_user_id=actor_user_id)

        invitation_url = self._build_invitation_url(invitation.public_id)
        invitation.delivery_state = TrustInvitationDeliveryState.QUEUED
        try:
            recipient = await UserRepository(self._session).get_by_email(
                invitation.subject_email.strip().lower()
            )
            await self._notifications.create_and_dispatch(
                NotificationRequest(
                    event_type="trust_invitation_received",
                    recipient_user_id=(
                        recipient.id
                        if recipient is not None
                        and recipient.is_active
                        and recipient.email_verified_at is not None
                        else None
                    ),
                    recipient_email=invitation.subject_email,
                    dedupe_key=(
                        f"trust-invitation:{invitation.public_id}:sent"
                        if trigger_event == TrustInvitationEventType.SENT
                        else None
                    ),
                    payload={
                        "organization_name": invitation.organization.name,
                        "subject_name": invitation.subject_name,
                        "invitation_url": invitation_url,
                        "expires_at_iso": invitation.expires_at.isoformat(),
                        "purpose": invitation.purpose,
                        "role": getattr(getattr(invitation, "job_role", None), "name", None),
                        "reminder": trigger_event == TrustInvitationEventType.RESENT,
                    },
                    metadata={
                        "trust_invitation_public_id": str(invitation.public_id),
                        "organization_public_id": str(invitation.organization.public_id),
                        "delivery_trigger": trigger_event.value,
                    },
                ),
                actor_user_id=actor_user_id,
            )
        except Exception as exc:
            invitation.delivery_state = TrustInvitationDeliveryState.FAILED
            await self._record_event(
                invitation,
                TrustInvitationEventType.DELIVERY_FAILED,
                actor_user_id=actor_user_id,
                metadata={
                    "delivery_trigger": trigger_event.value,
                    "error_type": type(exc).__name__,
                },
            )
            logger.warning(
                "trust_invitation_notification_delivery_failed",
                extra={
                    "event": "trust_invitation_notification_delivery_failed",
                    "invitation_public_id": str(invitation.public_id),
                    "delivery_trigger": trigger_event.value,
                    "error_type": type(exc).__name__,
                },
            )

    async def _record_event(
        self,
        invitation: TrustInvitation,
        event_type: TrustInvitationEventType,
        *,
        actor_user_id: UUID | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        await self._repo.add_event(
            TrustInvitationEvent(
                invitation_id=invitation.id,
                event_type=event_type.value,
                actor_user_id=actor_user_id,
                metadata_payload=metadata or {},
            )
        )

    async def _sync_person_link_best_effort(
        self,
        invitation_public_id: UUID,
        *,
        actor_user_id: UUID | None,
    ) -> None:
        try:
            invitation = await self._repo.get_by_public_id(
                invitation_public_id,
                include_events=True,
            )
            if invitation is None:
                return
            await self._people.resolve_for_trust_invitation(
                invitation,
                actor_user_id=actor_user_id,
            )
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            logger.warning(
                "trust_invitation_person_sync_failed",
                extra={
                    "event": "trust_invitation_person_sync_failed",
                    "invitation_public_id": str(invitation_public_id),
                    "actor_user_id": str(actor_user_id) if actor_user_id is not None else None,
                },
            )

    def _to_response(
        self,
        invitation: TrustInvitation,
        progress: list[TrustInvitationRequirementProgress] | None = None,
    ) -> TrustInvitationResponse:
        job_role = getattr(invitation, "job_role", None)
        progress = progress or []
        required = sum(1 for item in progress if item.mandatory)
        completed = sum(
            1 for item in progress if item.mandatory and item.status == "completed"
        )
        return TrustInvitationResponse(
            public_id=invitation.public_id,
            organization_public_id=invitation.organization.public_id,
            subject_name=invitation.subject_name,
            subject_email=_public_subject_email(invitation.subject_email),
            subject_phone=invitation.subject_phone,
            purpose=invitation.purpose,
            role_id=job_role.public_id if job_role is not None else None,
            role=job_role.name if job_role is not None else None,
            requested_verification_types=self._deserialize_verification_types(
                invitation.requested_verification_types
            ),
            message=invitation.message,
            status=invitation.status,
            delivery_method=invitation.delivery_method,
            delivery_state=invitation.delivery_state,
            created_by_email=invitation.created_by_user.email,
            created_by_full_name=invitation.created_by_user.full_name,
            expires_at=invitation.expires_at,
            sent_at=invitation.sent_at,
            opened_at=invitation.opened_at,
            accepted_at=invitation.accepted_at,
            cancelled_at=invitation.cancelled_at,
            related_verification_request_public_id=self._related_verification_request_public_id(
                invitation
            ),
            created_at=invitation.created_at,
            updated_at=invitation.updated_at,
            verification_preferences_snapshot=dict(
                getattr(invitation, "verification_preferences_snapshot", None) or {}
            ),
            requirements_snapshot=self._snapshot(invitation),
            requirements_version=getattr(invitation, "requirements_version", 1),
            lifecycle_state=self._lifecycle_state(invitation),
            declined_at=getattr(invitation, "declined_at", None),
            completed_at=getattr(invitation, "completed_at", None),
            completed_requirements=completed,
            required_requirements=(
                required
                if progress
                else sum(
                    1 for item in self._snapshot(invitation) if item.get("mandatory", True)
                )
            ),
            requirement_progress=progress,
        )

    async def _to_response_with_progress(
        self, invitation: TrustInvitation
    ) -> TrustInvitationResponse:
        progress: list[TrustInvitationRequirementProgress] = []
        accepted_by_user_id = getattr(invitation, "accepted_by_user_id", None)
        if accepted_by_user_id is not None:
            candidate = await UserRepository(self._session).get_by_id(accepted_by_user_id)
            if candidate is not None:
                progress = await self._requirement_progress(invitation, candidate)
        return self._to_response(invitation, progress)

    def _to_detail_response(
        self,
        invitation: TrustInvitation,
        progress: list[TrustInvitationRequirementProgress] | None = None,
    ) -> TrustInvitationDetailResponse:
        return TrustInvitationDetailResponse(
            **self._to_response(invitation, progress).model_dump(),
            invitation_url=self._build_invitation_url(invitation.public_id),
            timeline=[
                TrustInvitationTimelineEventResponse(
                    id=event.id,
                    event_type=TrustInvitationEventType(event.event_type),
                    occurred_at=event.occurred_at,
                    actor_user_id=event.actor_user_id,
                    actor_email=event.actor_user.email if event.actor_user is not None else None,
                    actor_full_name=(
                        event.actor_user.full_name if event.actor_user is not None else None
                    ),
                    metadata=event.metadata_payload,
                )
                for event in invitation.events
            ],
        )

    async def _to_detail_response_with_progress(
        self, invitation: TrustInvitation
    ) -> TrustInvitationDetailResponse:
        response = await self._to_response_with_progress(invitation)
        return TrustInvitationDetailResponse(
            **response.model_dump(),
            invitation_url=self._build_invitation_url(invitation.public_id),
            timeline=[
                TrustInvitationTimelineEventResponse(
                    id=event.id,
                    event_type=TrustInvitationEventType(event.event_type),
                    occurred_at=event.occurred_at,
                    actor_user_id=event.actor_user_id,
                    actor_email=event.actor_user.email if event.actor_user is not None else None,
                    actor_full_name=(
                        event.actor_user.full_name if event.actor_user is not None else None
                    ),
                    metadata=event.metadata_payload,
                )
                for event in invitation.events
            ],
        )

    def _related_verification_request_public_id(self, invitation: TrustInvitation) -> UUID | None:
        if not invitation.verification_requests:
            return None
        return invitation.verification_requests[0].public_id

    def _deserialize_verification_types(
        self,
        values: list[str],
    ) -> list[TrustInvitationVerificationType]:
        return [TrustInvitationVerificationType(value) for value in values]

    def _build_invitation_url(self, invitation_public_id: UUID) -> str:
        token = self._build_signed_token(invitation_public_id)
        return f"https://kairoid.com/invite/{token}"

    def _build_signed_token(self, invitation_public_id: UUID) -> str:
        body = invitation_public_id.hex
        signature = hmac.new(
            self._settings.jwt_secret_key.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"v2.{body}.{signature}"

    def _verify_signed_token(self, raw_token: str) -> UUID | None:
        prefix, separator, remainder = raw_token.partition(".")
        if prefix != "v2" or not separator:
            return None
        body, separator, signature = remainder.partition(".")
        if not separator or len(body) != 32 or not signature:
            return None
        try:
            invitation_public_id = UUID(hex=body)
        except ValueError:
            return None

        expected = hmac.new(
            self._settings.jwt_secret_key.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        return invitation_public_id

    def _normalize_email(self, email: str) -> str:
        return email.strip().lower()

    def _preference_snapshot(self, raw: dict[str, object] | None) -> dict[str, object]:
        defaults = DEFAULT_VERIFICATION_PREFERENCES
        raw = raw or {}
        checks = dict(defaults["checks"])
        if isinstance(raw.get("checks"), dict):
            checks.update({str(key): bool(value) for key, value in raw["checks"].items()})
        return {
            "version": int(raw.get("version", 1)),
            "checks": checks,
            "reference_count": int(raw.get("reference_count", 0)),
        }

    def _verification_types_from_preferences(
        self, preferences: dict[str, object]
    ) -> list[TrustInvitationVerificationType]:
        checks = preferences.get("checks")
        if not isinstance(checks, dict):
            return []
        if checks.get("address") is True:
            raise ValidationAppError(
                "Address is not supported by Trust Invitation orchestration. "
                "Choose explicit verification types or disable the address default; "
                "Permanent Address verification remains a separate workflow."
            )
        mapping = {
            "identity": TrustInvitationVerificationType.IDENTITY,
            "employment": TrustInvitationVerificationType.EMPLOYMENT,
            "education": TrustInvitationVerificationType.EDUCATION,
            "references": TrustInvitationVerificationType.PROFESSIONAL_REFERENCE,
        }
        return [value for key, value in mapping.items() if checks.get(key) is True]

    def _requirements_snapshot(self, supplied, requested_types) -> list[dict[str, object]]:  # noqa: ANN001
        if supplied is not None:
            return [
                {
                    "type": item.requirement_type.value,
                    "mandatory": item.mandatory,
                    "configuration": dict(item.configuration),
                }
                for item in supplied
            ]
        return [
            {"type": item.value, "mandatory": True, "configuration": {}} for item in requested_types
        ]

    def _snapshot(self, invitation: TrustInvitation) -> list[dict[str, object]]:
        snapshot = list(getattr(invitation, "requirements_snapshot", None) or [])
        if snapshot:
            return snapshot
        return [
            {"type": value, "mandatory": True, "configuration": {}}
            for value in invitation.requested_verification_types
        ]

    async def _require_verified_candidate(self, actor_user_id: UUID) -> User:
        user = await UserRepository(self._session).get_by_id(actor_user_id)
        if user is None or not user.is_active:
            raise NotFoundError("Candidate account not found")
        if user.email_verified_at is None:
            raise ForbiddenError("Verify your email before accessing Trust Invitations")
        return user

    async def _require_candidate_invitation(
        self, actor_user_id: UUID, invitation_public_id: UUID
    ) -> tuple[User, TrustInvitation]:
        user = await self._require_verified_candidate(actor_user_id)
        invitation = await self._repo.get_by_public_id(invitation_public_id)
        if invitation is None or invitation.status == TrustInvitationStatus.DRAFT:
            raise NotFoundError("Trust invitation not found")
        if self._normalize_email(user.email) != self._normalize_email(invitation.subject_email):
            raise NotFoundError("Trust invitation not found")
        if invitation.accepted_by_user_id not in {None, user.id}:
            raise NotFoundError("Trust invitation not found")
        if await self._expire_if_needed(invitation):
            await self._session.commit()
        return user, invitation

    async def _requirement_progress(
        self, invitation: TrustInvitation, user: User
    ) -> list[TrustInvitationRequirementProgress]:
        statuses: dict[str, tuple[str, str | None]] = {}
        identity_rows = list(
            (
                await self._session.scalars(
                    select(DigiLockerIdentityVerification).where(
                        DigiLockerIdentityVerification.user_id == user.id
                    )
                )
            ).all()
        )
        identity_ok = any(
            row.integrity_result == "verified"
            and row.match_result == "VERIFIED_MATCH"
            and row.verified_at is not None
            and row.profile_revision_at == user.updated_at
            and (
                row.document_valid_until is None
                or row.document_valid_until >= datetime.now(tz=UTC).date()
            )
            for row in identity_rows
        )
        statuses["identity"] = (
            "completed" if identity_ok else "action_required",
            None if identity_ok else "OPEN_IDENTITY",
        )
        model_specs = {
            "employment": (Employment, Employment.created_by_user_id, "OPEN_EMPLOYMENT"),
            "education": (Education, Education.user_id, "OPEN_EDUCATION"),
            "certification": (Certification, Certification.user_id, "OPEN_CERTIFICATION"),
        }
        for key, (model, owner_column, action) in model_specs.items():
            count = int(
                (
                    await self._session.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(
                            owner_column == user.id,
                            model.deleted_at.is_(None),
                            model.verification_status.in_(("verified", "approved")),
                        )
                    )
                )
                or 0
            )
            statuses[key] = ("completed" if count else "action_required", None if count else action)
        reference_count = int(
            (
                await self._session.scalar(
                    select(func.count())
                    .select_from(EmploymentReference)
                    .join(Employment, Employment.id == EmploymentReference.employment_id)
                    .where(
                        Employment.created_by_user_id == user.id,
                        EmploymentReference.active.is_(True),
                        EmploymentReference.status == "completed",
                    )
                )
            )
            or 0
        )
        statuses["professional_reference"] = (
            "completed" if reference_count else "action_required",
            None if reference_count else "OPEN_REFERENCES",
        )
        address_complete = bool(
            await self._session.scalar(
                select(PermanentAddressVersion.id)
                .where(
                    PermanentAddressVersion.user_id == user.id,
                    PermanentAddressVersion.completed_at.is_not(None),
                    PermanentAddressVersion.invalidated_at.is_(None),
                )
                .limit(1)
            )
        )
        statuses["permanent_address"] = (
            "completed" if address_complete else "action_required",
            None if address_complete else "OPEN_PERMANENT_ADDRESS",
        )
        progress: list[TrustInvitationRequirementProgress] = []
        for item in self._snapshot(invitation):
            requirement_type = str(item["type"])
            status, action = statuses.get(requirement_type, ("not_started", None))
            configuration = dict(item.get("configuration") or {})
            if requirement_type == "professional_reference":
                minimum = int(
                    configuration.get("minimum_count", configuration.get("reference_count", 1))
                )
                status = "completed" if reference_count >= minimum else "action_required"
                action = None if status == "completed" else "OPEN_REFERENCES"
            progress.append(
                TrustInvitationRequirementProgress(
                    requirement_type=TrustInvitationVerificationType(requirement_type),
                    mandatory=bool(item.get("mandatory", True)),
                    status=status,
                    action=action,
                    configuration=configuration,
                )
            )
        return progress

    async def _to_candidate_response(
        self, invitation: TrustInvitation, user: User
    ) -> CandidateTrustInvitationResponse:
        progress = await self._requirement_progress(invitation, user)
        required = sum(1 for item in progress if item.mandatory)
        completed = sum(1 for item in progress if item.mandatory and item.status == "completed")
        state = self._lifecycle_state(invitation)
        if state == "accepted" and completed < required:
            state = "in_progress"
        job_role = getattr(invitation, "job_role", None)
        return CandidateTrustInvitationResponse(
            public_id=invitation.public_id,
            organization_public_id=invitation.organization.public_id,
            organization_name=invitation.organization.name,
            role=job_role.name if job_role is not None else None,
            purpose=invitation.purpose,
            message=invitation.message,
            lifecycle_state=state,
            requirements_version=getattr(invitation, "requirements_version", 1),
            requirements=progress,
            completed_requirements=completed,
            required_requirements=required,
            accepted_at=invitation.accepted_at,
            declined_at=getattr(invitation, "declined_at", None),
            completed_at=getattr(invitation, "completed_at", None),
            expires_at=invitation.expires_at,
            share_action=(
                {
                    "action": "OPEN_PASSPORT",
                    "label": f"Share Passport with {invitation.organization.name}",
                }
                if invitation.accepted_at is not None
                and completed == required
                and state != "completed"
                else None
            ),
        )

    def _lifecycle_state(self, invitation: TrustInvitation) -> str:
        if getattr(invitation, "completed_at", None) is not None:
            return "completed"
        if getattr(invitation, "declined_at", None) is not None:
            return "declined"
        if invitation.status == TrustInvitationStatus.DRAFT:
            return "draft"
        if invitation.status == TrustInvitationStatus.CANCELLED:
            return "cancelled"
        if invitation.status == TrustInvitationStatus.EXPIRED:
            return "expired"
        if invitation.accepted_at is not None:
            return getattr(invitation, "candidate_state", None) or "accepted"
        return "available"

    def _assert_share_scope(self, invitation: TrustInvitation, share: PassportShareLink) -> None:
        permissions = dict(share.permissions or {})
        permission_by_type = {
            "identity": "include_profile",
            "employment": "include_employments",
            "education": "include_educations",
            "certification": "include_certifications",
        }
        missing = [
            item["type"]
            for item in self._snapshot(invitation)
            if item.get("mandatory", True)
            and item["type"] in permission_by_type
            and not permissions.get(permission_by_type[str(item["type"])], False)
        ]
        if missing:
            raise ConflictError("Passport share excludes mandatory invitation requirements")

    async def _notify_hr_lifecycle(
        self, invitation: TrustInvitation, event_type: str, actor_user_id: UUID
    ) -> None:
        try:
            await self._notifications.create_and_dispatch(
                NotificationRequest(
                    event_type=event_type,
                    channel="in_app",
                    recipient_user_id=invitation.created_by_user_id,
                    dedupe_key=f"trust-invitation:{invitation.public_id}:{event_type}",
                    payload={
                        "organization_name": invitation.organization.name,
                        "invitation_public_id": str(invitation.public_id),
                    },
                    metadata={
                        "trust_invitation_public_id": str(invitation.public_id),
                        "organization_public_id": str(invitation.organization.public_id),
                    },
                ),
                actor_user_id=actor_user_id,
            )
        except Exception:
            logger.exception(
                "trust_invitation_lifecycle_notification_failed",
                extra={
                    "event": "trust_invitation_lifecycle_notification_failed",
                    "invitation_public_id": str(invitation.public_id),
                    "notification_event_type": event_type,
                },
            )
