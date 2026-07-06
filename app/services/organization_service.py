"""Organization and membership use cases."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.organization.enums import OrganizationRole
from app.repositories.organization import OrganizationRepository
from app.repositories.user import UserRepository
from app.schemas.organization import (
    OrganizationCreateRequest,
    OrganizationMemberCreateRequest,
    OrganizationMemberResponse,
    OrganizationMemberUpdateRequest,
    OrganizationResponse,
)


class OrganizationService:
    """Organization management with membership-aware authorization helpers."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._organizations = OrganizationRepository(session)
        self._users = UserRepository(session)

    async def create_organization(
        self,
        actor_user_id: UUID,
        payload: OrganizationCreateRequest,
    ) -> OrganizationResponse:
        organization = Organization(
            created_by_user_id=actor_user_id,
            name=payload.name,
            organization_type=payload.organization_type,
            verification_capabilities=payload.verification_capabilities,
        )
        membership = OrganizationMember(
            organization=organization,
            user_id=actor_user_id,
            role=OrganizationRole.OWNER,
        )
        await self._organizations.create(organization, membership)
        await self._session.commit()
        await self._session.refresh(organization)
        await self._session.refresh(membership)
        return await self._to_organization_response(organization, membership)

    async def list_my_organizations(self, actor_user_id: UUID) -> list[OrganizationResponse]:
        rows = await self._organizations.list_for_user(actor_user_id)
        responses: list[OrganizationResponse] = []
        for organization, membership in rows:
            responses.append(await self._to_organization_response(organization, membership))
        return responses

    async def get_organization(self, actor_user_id: UUID, org_public_id: UUID) -> OrganizationResponse:
        organization, membership = await self.require_org_member(actor_user_id, org_public_id)
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
        await self._session.commit()
        refreshed = await self._organizations.get_member_by_public_id(organization.id, membership.public_id)
        if refreshed is None:
            raise NotFoundError("Organization member not found")
        return self._to_member_response(organization, refreshed)

    async def list_members(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
    ) -> list[OrganizationMemberResponse]:
        organization, _ = await self.require_org_member(actor_user_id, org_public_id)
        memberships = await self._organizations.list_members(organization.id)
        return [self._to_member_response(organization, membership) for membership in memberships]

    async def update_member_role(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        member_public_id: UUID,
        payload: OrganizationMemberUpdateRequest,
    ) -> OrganizationMemberResponse:
        organization, _ = await self.require_org_manager(actor_user_id, org_public_id)
        membership = await self._organizations.get_member_by_public_id(organization.id, member_public_id)
        if membership is None:
            raise NotFoundError("Organization member not found")
        if membership.role == OrganizationRole.OWNER:
            raise ForbiddenError("Owner membership cannot be changed through this endpoint")

        membership.role = payload.role
        await self._session.commit()
        refreshed = await self._organizations.get_member_by_public_id(organization.id, member_public_id)
        if refreshed is None:
            raise NotFoundError("Organization member not found")
        return self._to_member_response(organization, refreshed)

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
        if membership.role not in {OrganizationRole.OWNER, OrganizationRole.ADMIN}:
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
            created_at=membership.created_at,
            updated_at=membership.updated_at,
        )
