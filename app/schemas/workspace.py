"""Workspace bootstrap and organization invitation DTOs."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, EmailStr

from app.organization.enums import OrganizationInvitationStatus, OrganizationRole, OrganizationType, OrganizationVerificationState


class WorkspaceAccessState(StrEnum):
    READY = "ready"
    NO_ORG = "no_org"
    INVITATION_PENDING = "invitation_pending"
    SETUP_INCOMPLETE = "setup_incomplete"
    VERIFICATION_PENDING = "verification_pending"
    ORG_SUSPENDED = "org_suspended"
    MEMBERSHIP_SUSPENDED = "membership_suspended"


class WorkspaceCurrentUserResponse(BaseModel):
    id: UUID
    email: EmailStr
    full_name: str | None
    role: str
    active_organization_public_id: UUID | None


class WorkspacePermissionFlags(BaseModel):
    invite_candidate: bool
    modify_person: bool
    modify_invitation: bool
    modify_verification: bool
    manage_team: bool
    save_settings: bool
    transfer_ownership: bool


class WorkspaceOrganizationSummary(BaseModel):
    public_id: UUID
    name: str
    organization_type: OrganizationType
    website: str | None
    industry: str | None
    location: str | None
    work_email: EmailStr | None
    domain: str | None
    domain_verified_at: datetime | None
    verification_state: OrganizationVerificationState
    setup_completed_at: datetime | None
    suspended_at: datetime | None
    suspension_reason: str | None
    created_at: datetime
    updated_at: datetime


class WorkspaceOrganizationInvitationResponse(BaseModel):
    public_id: UUID
    organization_public_id: UUID
    organization_name: str
    invited_role: OrganizationRole
    invited_by_email: EmailStr
    invited_by_full_name: str | None
    status: OrganizationInvitationStatus
    invited_at: datetime
    expires_at: datetime | None
    accepted_at: datetime | None
    declined_at: datetime | None
    cancelled_at: datetime | None


class WorkspaceBootstrapResponse(BaseModel):
    state: WorkspaceAccessState
    current_user: WorkspaceCurrentUserResponse
    active_organization: WorkspaceOrganizationSummary | None
    membership_role: OrganizationRole | None
    organization_verification_state: OrganizationVerificationState | None
    organization_suspended: bool
    membership_suspended: bool
    setup_completed: bool
    pending_organization_invitation: WorkspaceOrganizationInvitationResponse | None
    permission_flags: WorkspacePermissionFlags
