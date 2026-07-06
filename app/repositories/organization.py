"""Repository for organizations and organization memberships."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.organization import Organization
from app.models.organization_member import OrganizationMember


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, organization: Organization, membership: OrganizationMember) -> Organization:
        self._session.add(organization)
        self._session.add(membership)
        await self._session.flush()
        return organization

    async def get_by_public_id(self, public_id: UUID) -> Organization | None:
        stmt = select(Organization).where(Organization.public_id == public_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(self, user_id: UUID) -> list[tuple[Organization, OrganizationMember]]:
        stmt = (
            select(Organization, OrganizationMember)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(OrganizationMember.user_id == user_id)
            .order_by(Organization.created_at.desc())
        )
        rows = await self._session.execute(stmt)
        return [(organization, membership) for organization, membership in rows.all()]

    async def count_members(self, organization_id: UUID) -> int:
        stmt = select(func.count()).select_from(OrganizationMember).where(OrganizationMember.organization_id == organization_id)
        return int((await self._session.execute(stmt)).scalar_one())

    async def get_membership(self, organization_id: UUID, user_id: UUID) -> OrganizationMember | None:
        stmt = (
            select(OrganizationMember)
            .options(joinedload(OrganizationMember.user))
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == user_id,
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_member_by_public_id(
        self,
        organization_id: UUID,
        member_public_id: UUID,
    ) -> OrganizationMember | None:
        stmt = (
            select(OrganizationMember)
            .options(joinedload(OrganizationMember.user))
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.public_id == member_public_id,
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_members(self, organization_id: UUID) -> list[OrganizationMember]:
        stmt = (
            select(OrganizationMember)
            .options(joinedload(OrganizationMember.user))
            .where(OrganizationMember.organization_id == organization_id)
            .order_by(OrganizationMember.created_at.asc())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())

    async def add_member(self, membership: OrganizationMember) -> OrganizationMember:
        self._session.add(membership)
        await self._session.flush()
        return membership
