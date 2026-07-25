"""Workspace bootstrap and invitation resolution for organization access."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.organization import Organization
from app.models.organization_invitation import OrganizationInvitation
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.organization.enums import OrganizationInvitationStatus, OrganizationVerificationState
from app.organization.permissions import build_workspace_permission_flags
from app.repositories.organization import OrganizationRepository
from app.repositories.organization_invitation import OrganizationInvitationRepository
from app.repositories.user import UserRepository
from app.schemas.workspace import (
    WorkspaceAccessState,
    WorkspaceBootstrapResponse,
    WorkspaceCurrentUserResponse,
    WorkspaceOrganizationInvitationResponse,
    WorkspaceOrganizationSummary,
    WorkspacePermissionFlags,
)


class WorkspaceService:
    """Resolve the current organization workspace for an authenticated user."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._organizations = OrganizationRepository(session)
        self._invitations = OrganizationInvitationRepository(session)
        self._users = UserRepository(session)

    async def bootstrap(self, actor_user_id: UUID) -> WorkspaceBootstrapResponse:
        user = await self._require_user(actor_user_id)
        now = datetime.now(tz=UTC)
        invitations = await self._invitations.list_for_invitee(
            invitee_email=self._normalize_email(user.email),
            invitee_user_id=user.id,
        )
        await self._expire_stale_invitations(invitations, now)

        organization, membership = await self._resolve_active_workspace(user)
        pending = self._first_pending_invitation(invitations, now)
        state = self._derive_state(organization, membership, pending)
        permission_flags = WorkspacePermissionFlags(
            **build_workspace_permission_flags(
                membership.role if membership is not None else None,
                organization_suspended=organization.suspended_at is not None if organization is not None else False,
                membership_suspended=membership.suspended_at is not None if membership is not None else False,
            )
        )

        return WorkspaceBootstrapResponse(
            state=state,
            current_user=WorkspaceCurrentUserResponse(
                id=user.id,
                email=user.email,
                full_name=user.full_name,
                role=user.role,
                active_organization_public_id=organization.public_id if organization is not None else None,
            ),
            active_organization=self._to_organization_summary(organization),
            membership_role=membership.role if membership is not None else None,
            organization_verification_state=organization.verification_state if organization is not None else None,
            organization_suspended=organization.suspended_at is not None if organization is not None else False,
            membership_suspended=membership.suspended_at is not None if membership is not None else False,
            setup_completed=organization.setup_completed_at is not None if organization is not None else False,
            pending_organization_invitation=self._to_invitation_response(pending),
            permission_flags=permission_flags,
        )

    async def list_invitations(self, actor_user_id: UUID) -> list[WorkspaceOrganizationInvitationResponse]:
        user = await self._require_user(actor_user_id)
        invitations = await self._invitations.list_for_invitee(
            invitee_email=self._normalize_email(user.email),
            invitee_user_id=user.id,
        )
        await self._expire_stale_invitations(invitations, datetime.now(tz=UTC))
        return [self._to_invitation_response(invitation) for invitation in invitations]

    async def accept_invitation(
        self,
        actor_user_id: UUID,
        invitation_public_id: UUID,
    ) -> WorkspaceOrganizationInvitationResponse:
        user = await self._require_user(actor_user_id)
        invitation = await self._require_invitation(invitation_public_id)
        now = datetime.now(tz=UTC)
        await self._expire_stale_invitations([invitation], now)
        self._assert_invitation_assignee(invitation, user)

        if invitation.status == OrganizationInvitationStatus.ACCEPTED:
            return self._to_invitation_response(invitation)
        if invitation.status != OrganizationInvitationStatus.PENDING:
            raise ConflictError("Organization invitation is no longer actionable")

        membership = await self._organizations.get_membership(invitation.organization_id, user.id)
        if membership is None:
            membership = OrganizationMember(
                organization_id=invitation.organization_id,
                user_id=user.id,
                role=invitation.role,
            )
            await self._organizations.add_member(membership)

        invitation.invitee_user_id = user.id
        invitation.status = OrganizationInvitationStatus.ACCEPTED
        invitation.accepted_at = now
        user.active_organization_id = invitation.organization_id

        await self._session.commit()
        refreshed = await self._invitations.get_by_public_id(invitation.public_id)
        if refreshed is None:
            raise NotFoundError("Organization invitation not found")
        return self._to_invitation_response(refreshed)

    async def decline_invitation(
        self,
        actor_user_id: UUID,
        invitation_public_id: UUID,
    ) -> WorkspaceOrganizationInvitationResponse:
        user = await self._require_user(actor_user_id)
        invitation = await self._require_invitation(invitation_public_id)
        now = datetime.now(tz=UTC)
        await self._expire_stale_invitations([invitation], now)
        self._assert_invitation_assignee(invitation, user)

        if invitation.status == OrganizationInvitationStatus.DECLINED:
            return self._to_invitation_response(invitation)
        if invitation.status != OrganizationInvitationStatus.PENDING:
            raise ConflictError("Organization invitation is no longer actionable")

        invitation.invitee_user_id = user.id
        invitation.status = OrganizationInvitationStatus.DECLINED
        invitation.declined_at = now

        await self._session.commit()
        refreshed = await self._invitations.get_by_public_id(invitation.public_id)
        if refreshed is None:
            raise NotFoundError("Organization invitation not found")
        return self._to_invitation_response(refreshed)

    async def _require_user(self, actor_user_id: UUID) -> User:
        user = await self._users.get_by_id(actor_user_id)
        if user is None:
            raise NotFoundError("User not found")
        return user

    async def _require_invitation(self, invitation_public_id: UUID) -> OrganizationInvitation:
        invitation = await self._invitations.get_by_public_id(invitation_public_id)
        if invitation is None:
            raise NotFoundError("Organization invitation not found")
        return invitation

    async def _resolve_active_workspace(
        self,
        user: User,
    ) -> tuple[Organization | None, OrganizationMember | None]:
        if user.active_organization_id is not None:
            organization = await self._organizations.get_by_id(user.active_organization_id)
            if organization is not None:
                membership = await self._organizations.get_membership(organization.id, user.id)
                if membership is not None:
                    return organization, membership

        memberships = await self._organizations.list_for_user(user.id)
        if not memberships:
            return None, None
        organization, membership = memberships[0]
        return organization, membership

    async def _expire_stale_invitations(
        self,
        invitations: list[OrganizationInvitation],
        now: datetime,
    ) -> None:
        changed = False
        for invitation in invitations:
            if invitation.status == OrganizationInvitationStatus.PENDING and invitation.expires_at is not None and invitation.expires_at <= now:
                invitation.status = OrganizationInvitationStatus.EXPIRED
                changed = True
        if changed:
            await self._session.commit()

    def _first_pending_invitation(
        self,
        invitations: list[OrganizationInvitation],
        now: datetime,
    ) -> OrganizationInvitation | None:
        for invitation in invitations:
            if (
                invitation.status == OrganizationInvitationStatus.PENDING
                and invitation.accepted_at is None
                and invitation.declined_at is None
                and invitation.cancelled_at is None
                and (invitation.expires_at is None or invitation.expires_at > now)
            ):
                return invitation
        return None

    def _assert_invitation_assignee(self, invitation: OrganizationInvitation, user: User) -> None:
        normalized_email = self._normalize_email(user.email)
        if normalized_email != invitation.invitee_email and invitation.invitee_user_id not in {None, user.id}:
            raise ForbiddenError("This organization invitation is not assigned to the authenticated account")
        if normalized_email != invitation.invitee_email and invitation.invitee_user_id is None:
            raise ForbiddenError("This organization invitation is not assigned to the authenticated account")

    def _derive_state(
        self,
        organization: Organization | None,
        membership: OrganizationMember | None,
        pending_invitation: OrganizationInvitation | None,
    ) -> WorkspaceAccessState:
        if membership is None or organization is None:
            if pending_invitation is not None:
                return WorkspaceAccessState.INVITATION_PENDING
            return WorkspaceAccessState.NO_ORG
        if membership.suspended_at is not None:
            return WorkspaceAccessState.MEMBERSHIP_SUSPENDED
        if organization.suspended_at is not None:
            return WorkspaceAccessState.ORG_SUSPENDED
        if organization.setup_completed_at is None or organization.verification_state == OrganizationVerificationState.SETUP_INCOMPLETE:
            return WorkspaceAccessState.SETUP_INCOMPLETE
        if organization.verification_state != OrganizationVerificationState.VERIFIED:
            return WorkspaceAccessState.VERIFICATION_PENDING
        return WorkspaceAccessState.READY

    def _to_organization_summary(self, organization: Organization | None) -> WorkspaceOrganizationSummary | None:
        if organization is None:
            return None
        return WorkspaceOrganizationSummary(
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
            created_at=organization.created_at,
            updated_at=organization.updated_at,
        )

    def _to_invitation_response(
        self,
        invitation: OrganizationInvitation | None,
    ) -> WorkspaceOrganizationInvitationResponse | None:
        if invitation is None:
            return None
        return WorkspaceOrganizationInvitationResponse(
            public_id=invitation.public_id,
            organization_public_id=invitation.organization.public_id,
            organization_name=invitation.organization.name,
            invited_role=invitation.role,
            invited_by_email=invitation.invited_by_user.email,
            invited_by_full_name=invitation.invited_by_user.full_name,
            status=invitation.status,
            invited_at=invitation.created_at,
            expires_at=invitation.expires_at,
            accepted_at=invitation.accepted_at,
            declined_at=invitation.declined_at,
            cancelled_at=invitation.cancelled_at,
        )

    def _normalize_email(self, email: str) -> str:
        return email.strip().lower()
