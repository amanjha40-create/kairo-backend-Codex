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
from app.organization.enums import OrganizationRole, OrganizationType
from app.schemas.organization import OrganizationMemberResponse, OrganizationResponse


class FakeOrganizationService:
    def __init__(self) -> None:
        self._org_public_id = uuid4()
        self._member_public_id = uuid4()
        self._now = datetime.now(tz=UTC)

    def _organization(self) -> OrganizationResponse:
        return OrganizationResponse(
            public_id=self._org_public_id,
            name="Kairo Labs",
            organization_type=OrganizationType.EMPLOYER,
            verification_capabilities=["employment"],
            my_role=OrganizationRole.OWNER,
            member_count=2,
            created_at=self._now,
            updated_at=self._now,
        )

    def _member(self, role: OrganizationRole = OrganizationRole.MEMBER) -> OrganizationMemberResponse:
        return OrganizationMemberResponse(
            public_id=self._member_public_id,
            organization_public_id=self._org_public_id,
            role=role,
            user_email="member@example.com",
            user_full_name="Team Member",
            created_at=self._now,
            updated_at=self._now,
        )

    async def create_organization(self, actor_user_id, payload):  # noqa: ANN001
        return self._organization()

    async def list_my_organizations(self, actor_user_id):  # noqa: ANN001
        return [self._organization()]

    async def get_organization(self, actor_user_id, org_public_id: UUID):  # noqa: ANN001
        if org_public_id == UUID("00000000-0000-0000-0000-00000000ffff"):
            raise NotFoundError("Organization not found")
        return self._organization()

    async def add_member(self, actor_user_id, org_public_id, payload):  # noqa: ANN001
        if payload.email == "duplicate@example.com":
            raise ConflictError("User is already a member of this organization")
        if payload.email == "blocked@example.com":
            raise ForbiddenError("Only organization owners or admins can manage members")
        return self._member(payload.role)

    async def list_members(self, actor_user_id, org_public_id):  # noqa: ANN001
        return [self._member(OrganizationRole.OWNER), self._member(OrganizationRole.REVIEWER)]

    async def update_member_role(self, actor_user_id, org_public_id, member_public_id: UUID, payload):  # noqa: ANN001
        if member_public_id == UUID("00000000-0000-0000-0000-00000000eeee"):
            raise ForbiddenError("Only organization owners or admins can manage members")
        return self._member(payload.role)


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
