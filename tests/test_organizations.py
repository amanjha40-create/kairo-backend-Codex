"""Route-contract tests for organization and membership management."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_organization_service
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.main import app
from app.organization.enums import (
    OrganizationInvitationStatus,
    OrganizationRole,
    OrganizationType,
    OrganizationVerificationState,
)
from app.schemas.organization import (
    OrganizationInvitationResponse,
    OrganizationMemberResponse,
    OrganizationOwnershipTransferResponse,
    OrganizationResponse,
)
from app.schemas.pagination import filter_sort_paginate


class FakeOrganizationService:
    def __init__(self) -> None:
        self._org_public_id = uuid4()
        self._member_public_id = uuid4()
        self._invitation_public_id = uuid4()
        self._now = datetime.now(tz=UTC)

    def _organization(self) -> OrganizationResponse:
        return OrganizationResponse(
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
            verification_capabilities=["employment"],
            my_role=OrganizationRole.OWNER,
            member_count=2,
            created_at=self._now,
            updated_at=self._now,
        )

    def _member(
        self, role: OrganizationRole = OrganizationRole.MEMBER
    ) -> OrganizationMemberResponse:
        return OrganizationMemberResponse(
            public_id=self._member_public_id,
            organization_public_id=self._org_public_id,
            role=role,
            user_email="member@example.com",
            user_full_name="Team Member",
            suspended_at=None,
            suspension_reason=None,
            created_at=self._now,
            updated_at=self._now,
        )

    def _invitation(
        self,
        *,
        status: OrganizationInvitationStatus = OrganizationInvitationStatus.PENDING,
    ) -> OrganizationInvitationResponse:
        return OrganizationInvitationResponse(
            public_id=self._invitation_public_id,
            organization_public_id=self._org_public_id,
            invitee_email="invitee@example.com",
            invitee_user_id=None,
            role=OrganizationRole.ADMIN,
            status=status,
            invited_by_email="owner@kairo.example",
            invited_by_full_name="Owner User",
            invited_at=self._now,
            expires_at=self._now,
            accepted_at=self._now if status == OrganizationInvitationStatus.ACCEPTED else None,
            declined_at=self._now if status == OrganizationInvitationStatus.DECLINED else None,
            cancelled_at=self._now if status == OrganizationInvitationStatus.CANCELLED else None,
            created_at=self._now,
            updated_at=self._now,
        )

    async def create_organization(self, actor_user_id, payload):  # noqa: ANN001
        return self._organization()

    async def complete_onboarding(self, actor_user_id, payload):  # noqa: ANN001
        return self._organization()

    async def list_my_organizations(self, actor_user_id, params=None):  # noqa: ANN001
        items = [self._organization()]
        if params:
            return filter_sort_paginate(
                items,
                params=params,
                search_fields=("name", "organization_type", "my_role"),
                allowed_sort_fields=("name", "created_at", "updated_at", "member_count"),
                default_sort_by="created_at",
            )
        return items

    async def get_organization(self, actor_user_id, org_public_id: UUID):  # noqa: ANN001
        if org_public_id == UUID("00000000-0000-0000-0000-00000000ffff"):
            raise NotFoundError("Organization not found")
        return self._organization()

    async def update_organization(self, actor_user_id, org_public_id, payload):  # noqa: ANN001
        if org_public_id == UUID("00000000-0000-0000-0000-00000000ffff"):
            raise NotFoundError("Organization not found")
        return self._organization()

    async def add_member(self, actor_user_id, org_public_id, payload):  # noqa: ANN001
        if payload.email == "duplicate@example.com":
            raise ConflictError("User is already a member of this organization")
        if payload.email == "blocked@example.com":
            raise ForbiddenError("Only organization owners or admins can manage members")
        return self._member(payload.role)

    async def list_members(self, actor_user_id, org_public_id, params=None):  # noqa: ANN001
        items = [self._member(OrganizationRole.OWNER), self._member(OrganizationRole.REVIEWER)]
        if params:
            return filter_sort_paginate(
                items,
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
        return items

    async def update_member_role(
        self, actor_user_id, org_public_id, member_public_id: UUID, payload
    ):  # noqa: ANN001
        if member_public_id == UUID("00000000-0000-0000-0000-00000000eeee"):
            raise ForbiddenError("Only organization owners or admins can manage members")
        return self._member(payload.role)

    async def create_invitation(self, actor_user_id, org_public_id, payload):  # noqa: ANN001
        if payload.invitee_email == "duplicate@example.com":
            raise ConflictError("An active invitation already exists for this email")
        return self._invitation()

    async def list_invitations(self, actor_user_id, org_public_id, params=None):  # noqa: ANN001
        items = [self._invitation(), self._invitation(status=OrganizationInvitationStatus.ACCEPTED)]
        if params:
            return filter_sort_paginate(
                items,
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
        return items

    async def resend_invitation(self, actor_user_id, org_public_id, invitation_public_id: UUID):  # noqa: ANN001
        if invitation_public_id == UUID("00000000-0000-0000-0000-00000000eeee"):
            raise ConflictError("Organization invitation is no longer actionable")
        return self._invitation()

    async def cancel_invitation(self, actor_user_id, org_public_id, invitation_public_id: UUID):  # noqa: ANN001
        if invitation_public_id == UUID("00000000-0000-0000-0000-00000000dddd"):
            raise ConflictError("Organization invitation is no longer actionable")
        return self._invitation(status=OrganizationInvitationStatus.CANCELLED)

    async def suspend_member(self, actor_user_id, org_public_id, member_public_id: UUID, payload):  # noqa: ANN001
        if member_public_id == UUID("00000000-0000-0000-0000-00000000cccc"):
            raise ConflictError("Cannot suspend the last active owner")
        return self._member()

    async def restore_member(self, actor_user_id, org_public_id, member_public_id: UUID):  # noqa: ANN001
        return self._member()

    async def remove_member(self, actor_user_id, org_public_id, member_public_id: UUID):  # noqa: ANN001
        if member_public_id == UUID("00000000-0000-0000-0000-00000000bbbb"):
            raise ConflictError("Cannot remove the last active owner")
        return None

    async def transfer_ownership(self, actor_user_id, org_public_id, member_public_id: UUID):  # noqa: ANN001
        if member_public_id == UUID("00000000-0000-0000-0000-00000000aaaa"):
            raise ForbiddenError("Only organization owners can transfer ownership")
        return OrganizationOwnershipTransferResponse(
            organization_public_id=self._org_public_id,
            previous_owner_member_public_id=self._member_public_id,
            new_owner_member_public_id=member_public_id,
            transferred_at=self._now,
        )


async def _override_current_user() -> CurrentUser:
    return CurrentUser(id=uuid4(), email="owner@example.com", role="user")


@pytest.mark.asyncio
async def test_create_organization_returns_owner_membership() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_service] = lambda: FakeOrganizationService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/organizations",
            json={
                "name": "Kairo Labs",
                "organization_type": "employer",
                "verification_capabilities": ["employment"],
            },
        )

    app.dependency_overrides.clear()
    assert response.status_code == 201
    body = response.json()
    assert body["my_role"] == "owner"
    assert body["public_id"]


@pytest.mark.asyncio
async def test_organization_onboarding_complete_returns_owner_membership() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_service] = lambda: FakeOrganizationService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/organizations/onboarding/complete",
            json={"name": "Kairo University", "organization_type": "university"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 201
    assert response.json()["my_role"] == "owner"


@pytest.mark.asyncio
async def test_list_my_organizations_returns_memberships() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_service] = lambda: FakeOrganizationService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/organizations/me")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["name"] == "Kairo Labs"


@pytest.mark.asyncio
async def test_list_my_organizations_supports_paginated_mode() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_service] = lambda: FakeOrganizationService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/organizations/me?paginate=true&page=1&page_size=10")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert len(body["items"]) == 1


@pytest.mark.asyncio
async def test_add_member_returns_created_member() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_service] = lambda: FakeOrganizationService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/organizations/{org_public_id}/members",
            json={"email": "member@example.com", "role": "reviewer"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 201
    body = response.json()
    assert body["role"] == "reviewer"
    assert body["organization_public_id"]


@pytest.mark.asyncio
async def test_list_members_returns_memberships() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_service] = lambda: FakeOrganizationService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/organizations/{org_public_id}/members")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["role"] == "owner"
    assert body[1]["role"] == "reviewer"


@pytest.mark.asyncio
async def test_list_members_supports_paginated_mode() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_service] = lambda: FakeOrganizationService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/organizations/{org_public_id}/members?paginate=true&page=1&page_size=1"
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["page_size"] == 1
    assert len(body["items"]) == 1


@pytest.mark.asyncio
async def test_duplicate_member_returns_conflict() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_service] = lambda: FakeOrganizationService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/organizations/{org_public_id}/members",
            json={"email": "duplicate@example.com", "role": "member"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


@pytest.mark.asyncio
async def test_non_member_cannot_view_organization() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_service] = lambda: FakeOrganizationService()

    transport = ASGITransport(app=app)
    blocked_public_id = "00000000-0000-0000-0000-00000000ffff"
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/organizations/{blocked_public_id}")

    app.dependency_overrides.clear()
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_member_without_manage_access_is_blocked() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_service] = lambda: FakeOrganizationService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/organizations/{org_public_id}/members",
            json={"email": "blocked@example.com", "role": "member"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


@pytest.mark.asyncio
async def test_update_organization_returns_updated_shape() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_service] = lambda: FakeOrganizationService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch(
            f"/api/v1/organizations/{org_public_id}",
            json={"website": "https://kairo.example", "domain": "kairo.example"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["website"] == "https://kairo.example"
    assert body["verification_state"] == "verification_pending"


@pytest.mark.asyncio
async def test_owner_can_update_member_role() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_service] = lambda: FakeOrganizationService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    member_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch(
            f"/api/v1/organizations/{org_public_id}/members/{member_public_id}",
            json={"role": "admin"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_create_invitation_returns_created_invitation() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_service] = lambda: FakeOrganizationService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/organizations/{org_public_id}/invitations",
            json={"invitee_email": "invitee@example.com", "role": "admin"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 201
    assert response.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_list_invitations_returns_invitation_history() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_service] = lambda: FakeOrganizationService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/organizations/{org_public_id}/invitations")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert len(response.json()) == 2


@pytest.mark.asyncio
async def test_resend_invitation_returns_updated_invitation() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_service] = lambda: FakeOrganizationService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    invitation_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/organizations/{org_public_id}/invitations/{invitation_public_id}/resend"
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_cancel_invitation_returns_cancelled_invitation() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_service] = lambda: FakeOrganizationService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    invitation_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/organizations/{org_public_id}/invitations/{invitation_public_id}/cancel"
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_suspend_member_returns_updated_member() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_service] = lambda: FakeOrganizationService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    member_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/organizations/{org_public_id}/members/{member_public_id}/suspend",
            json={"reason": "Left the organization"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["user_email"] == "member@example.com"


@pytest.mark.asyncio
async def test_restore_member_returns_updated_member() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_service] = lambda: FakeOrganizationService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    member_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/organizations/{org_public_id}/members/{member_public_id}/restore"
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_remove_member_returns_no_content() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_service] = lambda: FakeOrganizationService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    member_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete(
            f"/api/v1/organizations/{org_public_id}/members/{member_public_id}"
        )

    app.dependency_overrides.clear()
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_transfer_ownership_returns_transfer_shape() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_service] = lambda: FakeOrganizationService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    member_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/organizations/{org_public_id}/members/{member_public_id}/transfer-ownership"
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["new_owner_member_public_id"] == str(member_public_id)


def test_openapi_exposes_organization_team_lifecycle_paths() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/organizations/{org_public_id}/invitations" in paths
    assert (
        "/api/v1/organizations/{org_public_id}/invitations/{invitation_public_id}/resend" in paths
    )
    assert (
        "/api/v1/organizations/{org_public_id}/invitations/{invitation_public_id}/cancel" in paths
    )
    assert "/api/v1/organizations/{org_public_id}/members/{member_public_id}/suspend" in paths
    assert "/api/v1/organizations/{org_public_id}/members/{member_public_id}/restore" in paths
    assert (
        "/api/v1/organizations/{org_public_id}/members/{member_public_id}/transfer-ownership"
        in paths
    )
