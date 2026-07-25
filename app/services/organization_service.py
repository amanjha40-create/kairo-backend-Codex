"""Organization and membership use cases."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.models.organization import Organization
from app.models.organization_invitation import OrganizationInvitation
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.organization.enums import (
    OrganizationInvitationStatus,
    OrganizationRole,
    OrganizationType,
    OrganizationVerificationState,
)
from app.organization.permissions import is_organization_manager
from app.repositories.organization import OrganizationRepository
from app.repositories.organization_invitation import OrganizationInvitationRepository
from app.repositories.user import UserRepository
from app.schemas.organization import (
    OrganizationCreateRequest,
    OrganizationInvitationCreateRequest,
    OrganizationInvitationResponse,
    OrganizationMemberCreateRequest,
    OrganizationMemberResponse,
    OrganizationMemberSuspendRequest,
    OrganizationMemberUpdateRequest,
    OrganizationOwnershipTransferResponse,
    OrganizationResponse,
    OrganizationUpdateRequest,
)
from app.schemas.pagination import ListQueryParams, Page, filter_sort_paginate

INVITATION_TTL = timedelta(days=7)


class OrganizationService:
    """Organization management with membership-aware authorization helpers."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        organizations: OrganizationRepository | None = None,
        invitations: OrganizationInvitationRepository | None = None,
        users: UserRepository | None = None,
    ) -> None:
        self._session = session
        self._organizations = organizations or OrganizationRepository(session)
        self._invitations = invitations or OrganizationInvitationRepository(session)
        self._users = users or UserRepository(session)

    async def create_organization(
        self,
        actor_user_id: UUID,
        payload: OrganizationCreateRequest,
    ) -> OrganizationResponse:
        actor = await self._users.get_by_id(actor_user_id)
        if actor is None:
            raise NotFoundError("User not found")

        organization = Organization(
            created_by_user_id=actor_user_id,
            name=payload.name,
            organization_type=payload.organization_type,
            website=payload.website,
            industry=payload.industry,
            location=payload.location,
            work_email=str(payload.work_email).lower() if payload.work_email is not None else None,
            domain=payload.domain,
            organization_size=payload.organization_size,
            hiring_volume=payload.hiring_volume,
            verification_capabilities=payload.verification_capabilities,
        )
        self._apply_setup_state(organization)
        membership = OrganizationMember(
            organization=organization,
            user_id=actor_user_id,
            role=OrganizationRole.OWNER,
        )
        await self._organizations.create(organization, membership)
        actor.active_organization_id = organization.id
        await self._session.commit()
        await self._session.refresh(organization)
        await self._session.refresh(membership)
        return await self._to_organization_response(organization, membership)

    async def complete_onboarding(
        self,
        actor_user_id: UUID,
        payload: OrganizationCreateRequest,
    ) -> OrganizationResponse:
        """Create the first organization for an authenticated workspace user."""

        if payload.organization_type not in {
            OrganizationType.EMPLOYER,
            OrganizationType.UNIVERSITY,
        }:
            raise ValidationAppError(
                "Organization onboarding supports employer or university workspaces"
            )
        existing = await self._organizations.list_for_user(actor_user_id)
        if existing:
            raise ConflictError("Organization onboarding is already complete")
        return await self.create_organization(actor_user_id, payload)

    async def list_my_organizations(
        self,
        actor_user_id: UUID,
        params: ListQueryParams | None = None,
    ) -> list[OrganizationResponse] | Page[OrganizationResponse]:
        rows = await self._organizations.list_for_user(actor_user_id)
        responses: list[OrganizationResponse] = []
        for organization, membership in rows:
            responses.append(await self._to_organization_response(organization, membership))
        if params is None:
            return responses
        return filter_sort_paginate(
            responses,
            params=params,
            search_fields=("name", "organization_type", "my_role"),
            allowed_sort_fields=("name", "created_at", "updated_at", "member_count"),
            default_sort_by="created_at",
        )

    async def get_organization(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
    ) -> OrganizationResponse:
        organization, membership = await self.require_org_member(actor_user_id, org_public_id)
        return await self._to_organization_response(organization, membership)

    async def update_organization(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        payload: OrganizationUpdateRequest,
    ) -> OrganizationResponse:
        organization, membership = await self.require_org_manager(actor_user_id, org_public_id)

        if payload.name is not None:
            organization.name = payload.name
        if payload.organization_type is not None:
            organization.organization_type = payload.organization_type
        if payload.website is not None:
            organization.website = payload.website
        if payload.industry is not None:
            organization.industry = payload.industry
        if payload.location is not None:
            organization.location = payload.location
        if payload.work_email is not None:
            organization.work_email = str(payload.work_email).lower()
        if payload.domain is not None:
            organization.domain = payload.domain
        if payload.verification_capabilities is not None:
            organization.verification_capabilities = payload.verification_capabilities
        if payload.organization_size is not None:
            organization.organization_size = payload.organization_size
        if payload.hiring_volume is not None:
            organization.hiring_volume = payload.hiring_volume

        self._apply_setup_state(organization)
        await self._session.commit()
        await self._session.refresh(organization)
        return await self._to_organization_response(organization, membership)

    async def add_member(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        payload: OrganizationMemberCreateRequest,
    ) -> OrganizationMemberResponse:
        organization, _ = await self.require_org_manager(actor_user_id, org_public_id)
        user = await self._users.get_by_email(payload.email)
        if user is None:
            raise NotFoundError("User not found")

        existing = await self._organizations.get_membership(organization.id, user.id)
        if existing is not None:
            raise ConflictError("User is already a member of this organization")

        membership = OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role=payload.role,
        )
        await self._organizations.add_member(membership)
        await self._cancel_superseded_pending_invitations(organization.id, user.email)
        await self._session.commit()
        refreshed = await self._organizations.get_member_by_public_id(
            organization.id,
            membership.public_id,
        )
        if refreshed is None:
            raise NotFoundError("Organization member not found")
        return self._to_member_response(organization, refreshed)

    async def list_members(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        params: ListQueryParams | None = None,
    ) -> list[OrganizationMemberResponse] | Page[OrganizationMemberResponse]:
        organization, _ = await self.require_org_member(actor_user_id, org_public_id)
        memberships = await self._organizations.list_members(organization.id)
        responses = [
            self._to_member_response(organization, membership)
            for membership in memberships
        ]
        if params is None:
            return responses
        return filter_sort_paginate(
            responses,
            params=params,
            search_fields=("user_email", "user_full_name", "role"),
            allowed_sort_fields=(
                "created_at",
                "updated_at",
                "role",
                "user_email",
                "user_full_name",
            ),
            default_sort_by="created_at",
        )

    async def update_member_role(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        member_public_id: UUID,
        payload: OrganizationMemberUpdateRequest,
    ) -> OrganizationMemberResponse:
        organization, _ = await self.require_org_manager(actor_user_id, org_public_id)
        membership = await self._organizations.get_member_by_public_id(
            organization.id,
            member_public_id,
        )
        if membership is None:
            raise NotFoundError("Organization member not found")
        if membership.role == OrganizationRole.OWNER:
            raise ForbiddenError("Owner membership cannot be changed through this endpoint")

        membership.role = payload.role
        await self._session.commit()
        refreshed = await self._organizations.get_member_by_public_id(
            organization.id,
            member_public_id,
        )
        if refreshed is None:
            raise NotFoundError("Organization member not found")
        return self._to_member_response(organization, refreshed)

    async def create_invitation(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        payload: OrganizationInvitationCreateRequest,
    ) -> OrganizationInvitationResponse:
        organization, _ = await self.require_org_manager(actor_user_id, org_public_id)
        invitee_email = self._normalize_email(str(payload.invitee_email))
        user = await self._users.get_by_email(invitee_email)

        if user is not None:
            existing_membership = await self._organizations.get_membership(organization.id, user.id)
            if existing_membership is not None:
                raise ConflictError("User already has a membership in this organization")

        pending = await self._invitations.list_active_pending_for_organization_email(
            organization_id=organization.id,
            invitee_email=invitee_email,
        )
        await self._expire_stale_invitations(pending, datetime.now(tz=UTC))
        active_pending = [
            invitation
            for invitation in pending
            if self._is_invitation_actionable(invitation)
        ]
        if active_pending:
            raise ConflictError("An active invitation already exists for this email")

        invitation = OrganizationInvitation(
            organization_id=organization.id,
            invited_by_user_id=actor_user_id,
            invitee_user_id=user.id if user is not None else None,
            invitee_email=invitee_email,
            role=payload.role,
            status=OrganizationInvitationStatus.PENDING,
            expires_at=datetime.now(tz=UTC) + INVITATION_TTL,
        )
        await self._invitations.create(invitation)
        await self._session.commit()

        refreshed = await self._invitations.get_by_public_id_for_organization(
            organization.id,
            invitation.public_id,
        )
        if refreshed is None:
            raise NotFoundError("Organization invitation not found")
        return self._to_invitation_response(refreshed)

    async def list_invitations(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        params: ListQueryParams | None = None,
    ) -> list[OrganizationInvitationResponse] | Page[OrganizationInvitationResponse]:
        organization, _ = await self.require_org_manager(actor_user_id, org_public_id)
        invitations = await self._invitations.list_for_organization(organization.id)
        await self._expire_stale_invitations(invitations, datetime.now(tz=UTC))
        responses = [self._to_invitation_response(invitation) for invitation in invitations]
        if params is None:
            return responses
        return filter_sort_paginate(
            responses,
            params=params,
            search_fields=("invitee_email", "invited_by_email", "role", "status"),
            allowed_sort_fields=(
                "created_at",
                "updated_at",
                "expires_at",
                "invitee_email",
                "role",
                "status",
            ),
            default_sort_by="created_at",
        )

    async def resend_invitation(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        invitation_public_id: UUID,
    ) -> OrganizationInvitationResponse:
        organization, _ = await self.require_org_manager(actor_user_id, org_public_id)
        invitation = await self._require_org_invitation(organization.id, invitation_public_id)
        await self._expire_stale_invitations([invitation], datetime.now(tz=UTC))

        if invitation.status != OrganizationInvitationStatus.PENDING:
            raise ConflictError("Organization invitation is no longer actionable")

        if invitation.invitee_user_id is None:
            user = await self._users.get_by_email(invitation.invitee_email)
            if user is not None:
                invitation.invitee_user_id = user.id
        if invitation.invitee_user_id is not None:
            membership = await self._organizations.get_membership(
                organization.id,
                invitation.invitee_user_id,
            )
            if membership is not None:
                raise ConflictError("User already has a membership in this organization")

        invitation.expires_at = datetime.now(tz=UTC) + INVITATION_TTL
        await self._session.commit()

        refreshed = await self._invitations.get_by_public_id_for_organization(
            organization.id,
            invitation.public_id,
        )
        if refreshed is None:
            raise NotFoundError("Organization invitation not found")
        return self._to_invitation_response(refreshed)

    async def cancel_invitation(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        invitation_public_id: UUID,
    ) -> OrganizationInvitationResponse:
        organization, _ = await self.require_org_manager(actor_user_id, org_public_id)
        invitation = await self._require_org_invitation(organization.id, invitation_public_id)
        await self._expire_stale_invitations([invitation], datetime.now(tz=UTC))

        if invitation.status == OrganizationInvitationStatus.CANCELLED:
            return self._to_invitation_response(invitation)
        if invitation.status in {
            OrganizationInvitationStatus.ACCEPTED,
            OrganizationInvitationStatus.DECLINED,
        }:
            raise ConflictError("Organization invitation is no longer actionable")
        if invitation.status != OrganizationInvitationStatus.PENDING:
            raise ConflictError("Organization invitation is no longer actionable")

        invitation.status = OrganizationInvitationStatus.CANCELLED
        invitation.cancelled_at = datetime.now(tz=UTC)
        await self._session.commit()

        refreshed = await self._invitations.get_by_public_id_for_organization(
            organization.id,
            invitation.public_id,
        )
        if refreshed is None:
            raise NotFoundError("Organization invitation not found")
        return self._to_invitation_response(refreshed)

    async def suspend_member(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        member_public_id: UUID,
        payload: OrganizationMemberSuspendRequest,
    ) -> OrganizationMemberResponse:
        organization, actor_membership = await self.require_org_manager(
            actor_user_id,
            org_public_id,
        )
        membership = await self._require_org_member_by_public_id(organization.id, member_public_id)
        self._assert_member_action_allowed(actor_membership, membership)
        await self._ensure_not_last_active_owner(organization.id, membership, action="suspend")

        if membership.suspended_at is None:
            membership.suspended_at = datetime.now(tz=UTC)
        membership.suspension_reason = payload.reason
        await self._reassign_active_organization_if_needed(membership.user, organization.id)
        await self._session.commit()

        refreshed = await self._organizations.get_member_by_public_id(
            organization.id,
            member_public_id,
        )
        if refreshed is None:
            raise NotFoundError("Organization member not found")
        return self._to_member_response(organization, refreshed)

    async def restore_member(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        member_public_id: UUID,
    ) -> OrganizationMemberResponse:
        organization, actor_membership = await self.require_org_manager(
            actor_user_id,
            org_public_id,
        )
        membership = await self._require_org_member_by_public_id(organization.id, member_public_id)
        self._assert_member_action_allowed(actor_membership, membership)

        membership.suspended_at = None
        membership.suspension_reason = None
        await self._session.commit()

        refreshed = await self._organizations.get_member_by_public_id(
            organization.id,
            member_public_id,
        )
        if refreshed is None:
            raise NotFoundError("Organization member not found")
        return self._to_member_response(organization, refreshed)

    async def remove_member(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        member_public_id: UUID,
    ) -> None:
        organization, actor_membership = await self.require_org_manager(
            actor_user_id,
            org_public_id,
        )
        membership = await self._require_org_member_by_public_id(organization.id, member_public_id)
        self._assert_member_action_allowed(actor_membership, membership)
        await self._ensure_not_last_active_owner(organization.id, membership, action="remove")

        await self._reassign_active_organization_if_needed(membership.user, organization.id)
        await self._organizations.delete_member(membership)
        await self._session.commit()

    async def transfer_ownership(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        member_public_id: UUID,
    ) -> OrganizationOwnershipTransferResponse:
        organization, actor_membership = await self.require_org_member(actor_user_id, org_public_id)
        if actor_membership.role != OrganizationRole.OWNER:
            raise ForbiddenError("Only organization owners can transfer ownership")

        membership = await self._require_org_member_by_public_id(organization.id, member_public_id)
        if membership.id == actor_membership.id:
            raise ConflictError("Ownership cannot be transferred to the current owner")
        if membership.role == OrganizationRole.OWNER:
            raise ConflictError("Target member is already an owner")
        if membership.suspended_at is not None:
            raise ConflictError("Ownership can only be transferred to an active member")

        transferred_at = datetime.now(tz=UTC)
        actor_membership.role = OrganizationRole.ADMIN
        membership.role = OrganizationRole.OWNER
        await self._session.commit()

        return OrganizationOwnershipTransferResponse(
            organization_public_id=organization.public_id,
            previous_owner_member_public_id=actor_membership.public_id,
            new_owner_member_public_id=membership.public_id,
            transferred_at=transferred_at,
        )

    async def require_org_member(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
    ) -> tuple[Organization, OrganizationMember]:
        organization = await self._organizations.get_by_public_id(org_public_id)
        if organization is None:
            raise NotFoundError("Organization not found")

        membership = await self._organizations.get_membership(organization.id, actor_user_id)
        if membership is None:
            raise NotFoundError("Organization not found")

        return organization, membership

    async def require_org_manager(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
    ) -> tuple[Organization, OrganizationMember]:
        organization, membership = await self.require_org_member(actor_user_id, org_public_id)
        if not is_organization_manager(membership.role):
            raise ForbiddenError("Only organization owners or admins can manage members")
        return organization, membership

    async def _to_organization_response(
        self,
        organization: Organization,
        membership: OrganizationMember,
    ) -> OrganizationResponse:
        member_count = await self._organizations.count_members(organization.id)
        return OrganizationResponse(
            public_id=organization.public_id,
            name=organization.name,
            organization_type=organization.organization_type,
            website=organization.website,
            industry=organization.industry,
            location=organization.location,
            work_email=organization.work_email,
            domain=organization.domain,
            organization_size=organization.organization_size,
            hiring_volume=organization.hiring_volume,
            domain_verified_at=organization.domain_verified_at,
            verification_state=organization.verification_state,
            setup_completed_at=organization.setup_completed_at,
            suspended_at=organization.suspended_at,
            suspension_reason=organization.suspension_reason,
            verification_capabilities=list(organization.verification_capabilities or []),
            my_role=membership.role,
            member_count=member_count,
            created_at=organization.created_at,
            updated_at=organization.updated_at,
        )

    def _to_member_response(
        self,
        organization: Organization,
        membership: OrganizationMember,
    ) -> OrganizationMemberResponse:
        return OrganizationMemberResponse(
            public_id=membership.public_id,
            organization_public_id=organization.public_id,
            role=membership.role,
            user_email=membership.user.email,
            user_full_name=membership.user.full_name,
            suspended_at=membership.suspended_at,
            suspension_reason=membership.suspension_reason,
            created_at=membership.created_at,
            updated_at=membership.updated_at,
        )

    def _to_invitation_response(
        self,
        invitation: OrganizationInvitation,
    ) -> OrganizationInvitationResponse:
        return OrganizationInvitationResponse(
            public_id=invitation.public_id,
            organization_public_id=invitation.organization.public_id,
            invitee_email=invitation.invitee_email,
            invitee_user_id=invitation.invitee_user_id,
            role=invitation.role,
            status=invitation.status,
            invited_by_email=invitation.invited_by_user.email,
            invited_by_full_name=invitation.invited_by_user.full_name,
            invited_at=invitation.created_at,
            expires_at=invitation.expires_at,
            accepted_at=invitation.accepted_at,
            declined_at=invitation.declined_at,
            cancelled_at=invitation.cancelled_at,
            created_at=invitation.created_at,
            updated_at=invitation.updated_at,
        )

    def _apply_setup_state(self, organization: Organization) -> None:
        has_required_setup = bool(
            organization.name
            and organization.organization_type
            and organization.work_email
            and organization.domain
        )
        if not has_required_setup:
            return
        if organization.setup_completed_at is None:
            organization.setup_completed_at = datetime.now(tz=UTC)
        if organization.verification_state == OrganizationVerificationState.SETUP_INCOMPLETE:
            organization.verification_state = OrganizationVerificationState.VERIFICATION_PENDING

    async def _require_org_member_by_public_id(
        self,
        organization_id: UUID,
        member_public_id: UUID,
    ) -> OrganizationMember:
        membership = await self._organizations.get_member_by_public_id(
            organization_id,
            member_public_id,
        )
        if membership is None:
            raise NotFoundError("Organization member not found")
        return membership

    async def _require_org_invitation(
        self,
        organization_id: UUID,
        invitation_public_id: UUID,
    ) -> OrganizationInvitation:
        invitation = await self._invitations.get_by_public_id_for_organization(
            organization_id,
            invitation_public_id,
        )
        if invitation is None:
            raise NotFoundError("Organization invitation not found")
        return invitation

    def _assert_member_action_allowed(
        self,
        actor_membership: OrganizationMember,
        target_membership: OrganizationMember,
    ) -> None:
        if (
            target_membership.role == OrganizationRole.OWNER
            and actor_membership.role != OrganizationRole.OWNER
        ):
            raise ForbiddenError("Admins cannot affect owner memberships")

    async def _ensure_not_last_active_owner(
        self,
        organization_id: UUID,
        membership: OrganizationMember,
        *,
        action: str,
    ) -> None:
        if membership.role != OrganizationRole.OWNER or membership.suspended_at is not None:
            return
        active_owners = await self._organizations.count_active_owners(organization_id)
        if active_owners <= 1:
            raise ConflictError(f"Cannot {action} the last active owner")

    async def _expire_stale_invitations(
        self,
        invitations: list[OrganizationInvitation],
        now: datetime,
    ) -> None:
        changed = False
        for invitation in invitations:
            if (
                invitation.status == OrganizationInvitationStatus.PENDING
                and invitation.expires_at is not None
                and invitation.expires_at <= now
            ):
                invitation.status = OrganizationInvitationStatus.EXPIRED
                changed = True
        if changed:
            await self._session.flush()

    def _is_invitation_actionable(self, invitation: OrganizationInvitation) -> bool:
        return (
            invitation.status == OrganizationInvitationStatus.PENDING
            and invitation.accepted_at is None
            and invitation.declined_at is None
            and invitation.cancelled_at is None
        )

    async def _cancel_superseded_pending_invitations(
        self,
        organization_id: UUID,
        invitee_email: str,
    ) -> None:
        invitations = await self._invitations.list_active_pending_for_organization_email(
            organization_id=organization_id,
            invitee_email=self._normalize_email(invitee_email),
        )
        await self._expire_stale_invitations(invitations, datetime.now(tz=UTC))
        for invitation in invitations:
            if self._is_invitation_actionable(invitation):
                invitation.status = OrganizationInvitationStatus.CANCELLED
                invitation.cancelled_at = datetime.now(tz=UTC)

    async def _reassign_active_organization_if_needed(
        self,
        user: User,
        organization_id: UUID,
    ) -> None:
        if user.active_organization_id != organization_id:
            return

        memberships = await self._organizations.list_for_user(user.id)
        for organization, membership in memberships:
            if organization.id == organization_id:
                continue
            if membership.suspended_at is None:
                user.active_organization_id = organization.id
                return

        user.active_organization_id = None

    def _normalize_email(self, value: str) -> str:
        return value.strip().lower()
