"""Route-contract tests for workspace bootstrap and organization invitations."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_workspace_service
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.main import app
from app.organization.enums import (
    OrganizationInvitationStatus,
    OrganizationRole,
    OrganizationType,
    OrganizationVerificationState,
)
from app.schemas.workspace import (
    WorkspaceAccessState,
    WorkspaceBootstrapResponse,
    WorkspaceCurrentUserResponse,
    WorkspaceOrganizationInvitationResponse,
    WorkspaceOrganizationSummary,
    WorkspacePermissionFlags,
)


class FakeWorkspaceService:
    def __init__(self) -> None:
        self._org_public_id = uuid4()
        self._invitation_public_id = uuid4()
        self._now = datetime.now(tz=UTC)

    def _invitation(self, status: OrganizationInvitationStatus = OrganizationInvitationStatus.PENDING) -> WorkspaceOrganizationInvitationResponse:
        return WorkspaceOrganizationInvitationResponse(
            public_id=self._invitation_public_id,
            organization_public_id=self._org_public_id,
            organization_name="Kairo Labs",
            invited_role=OrganizationRole.ADMIN,
            invited_by_email="owner@kairo.example",
            invited_by_full_name="Owner User",
            status=status,
            invited_at=self._now,
            expires_at=None,
            accepted_at=self._now if status == OrganizationInvitationStatus.ACCEPTED else None,
            declined_at=self._now if status == OrganizationInvitationStatus.DECLINED else None,
            cancelled_at=None,
        )

    def _bootstrap(self) -> WorkspaceBootstrapResponse:
        return WorkspaceBootstrapResponse(
            state=WorkspaceAccessState.VERIFICATION_PENDING,
            current_user=WorkspaceCurrentUserResponse(
                id=uuid4(),
                email="owner@kairo.example",
                full_name="Owner User",
                role="user",
                active_organization_public_id=self._org_public_id,
            ),
            active_organization=WorkspaceOrganizationSummary(
                public_id=self._org_public_id,
                name="Kairo Labs",
                organization_type=OrganizationType.EMPLOYER,
                website="https://kairo.example",
                industry="Software",
                location="Bengaluru, IN",
                work_email="owner@kairo.example",
                domain="kairo.example",
                organization_size=None,
                hiring_volume=None,
                domain_verified_at=None,
                verification_state=OrganizationVerificationState.VERIFICATION_PENDING,
                setup_completed_at=self._now,
                suspended_at=None,
                suspension_reason=None,
                created_at=self._now,
                updated_at=self._now,
            ),
            membership_role=OrganizationRole.OWNER,
            organization_verification_state=OrganizationVerificationState.VERIFICATION_PENDING,
            organization_suspended=False,
            membership_suspended=False,
            setup_completed=True,
            pending_organization_invitation=self._invitation(),
            permission_flags=WorkspacePermissionFlags(
                invite_candidate=True,
                modify_person=True,
                modify_invitation=True,
                modify_verification=True,
                manage_team=True,
                save_settings=True,
                transfer_ownership=True,
            ),
        )

    async def bootstrap(self, actor_user_id):  # noqa: ANN001
        return self._bootstrap()

    async def list_invitations(self, actor_user_id):  # noqa: ANN001
        return [self._invitation(), self._invitation(OrganizationInvitationStatus.ACCEPTED)]

    async def accept_invitation(self, actor_user_id, invitation_public_id: UUID):  # noqa: ANN001
        if invitation_public_id == UUID("00000000-0000-0000-0000-00000000ffff"):
            raise NotFoundError("Organization invitation not found")
        if invitation_public_id == UUID("00000000-0000-0000-0000-00000000eeee"):
            raise ForbiddenError("This organization invitation is not assigned to the authenticated account")
        if invitation_public_id == UUID("00000000-0000-0000-0000-00000000dddd"):
            raise ConflictError("Organization invitation is no longer actionable")
        return self._invitation(OrganizationInvitationStatus.ACCEPTED)

    async def decline_invitation(self, actor_user_id, invitation_public_id: UUID):  # noqa: ANN001
        if invitation_public_id == UUID("00000000-0000-0000-0000-00000000ffff"):
            raise NotFoundError("Organization invitation not found")
        return self._invitation(OrganizationInvitationStatus.DECLINED)


async def _override_current_user() -> CurrentUser:
    return CurrentUser(id=uuid4(), email="owner@kairo.example", role="user")


@pytest.mark.asyncio
async def test_workspace_bootstrap_returns_authoritative_state() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_workspace_service] = lambda: FakeWorkspaceService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/workspace/bootstrap")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "verification_pending"
    assert body["active_organization"]["name"] == "Kairo Labs"
    assert body["permission_flags"]["manage_team"] is True


@pytest.mark.asyncio
async def test_workspace_invitation_listing_returns_statuses() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_workspace_service] = lambda: FakeWorkspaceService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/workspace/invitations")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_accept_workspace_invitation_maps_conflicts() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_workspace_service] = lambda: FakeWorkspaceService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/workspace/invitations/00000000-0000-0000-0000-00000000dddd/accept")

    app.dependency_overrides.clear()
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


@pytest.mark.asyncio
async def test_decline_workspace_invitation_returns_declined_status() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_workspace_service] = lambda: FakeWorkspaceService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/v1/workspace/invitations/{uuid4()}/decline")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "declined"
