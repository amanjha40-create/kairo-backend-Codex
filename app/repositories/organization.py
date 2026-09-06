"""Repository for organizations and organization memberships."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.trust_registry_alias import TrustRegistryAlias
from app.models.trust_registry_domain import TrustRegistryDomain
from app.models.trust_registry_identifier import TrustRegistryIdentifier
from app.models.trust_registry_record import TrustRegistryRecord
from app.organization.enums import OrganizationRole


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, organization: Organization, membership: OrganizationMember
    ) -> Organization:
        self._session.add(organization)
        self._session.add(membership)
        await self._session.flush()
        return organization

    async def create_canonical(self, organization: Organization) -> Organization:
        """Create an Admin-owned canonical organization without tenant membership."""

        self._session.add(organization)
        await self._session.flush()
        return organization

    async def get_by_public_id(self, public_id: UUID) -> Organization | None:
        stmt = select(Organization).where(Organization.public_id == public_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(self, organization_id: UUID) -> Organization | None:
        stmt = select(Organization).where(Organization.id == organization_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_registry_record_id(self, registry_record_id: UUID) -> Organization | None:
        stmt = (
            select(Organization)
            .options(joinedload(Organization.registry_record))
            .where(Organization.registry_record_id == registry_record_id)
            .order_by(Organization.created_at.asc())
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def find_exact(self, *, name: str, domain: str | None) -> Organization | None:
        filters = [func.lower(Organization.name) == name.strip().lower()]
        if domain:
            filters.append(func.lower(Organization.domain) == domain.strip().lower())
        stmt = (
            select(Organization)
            .options(joinedload(Organization.registry_record))
            .where(or_(*filters))
            .order_by(Organization.created_at.asc())
        )
        return (await self._session.execute(stmt)).scalars().first()

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
        stmt = (
            select(func.count())
            .select_from(OrganizationMember)
            .where(OrganizationMember.organization_id == organization_id)
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def get_membership(
        self, organization_id: UUID, user_id: UUID
    ) -> OrganizationMember | None:
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

    async def count_active_owners(self, organization_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(OrganizationMember)
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.role == OrganizationRole.OWNER,
                OrganizationMember.suspended_at.is_(None),
            )
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def add_member(self, membership: OrganizationMember) -> OrganizationMember:
        self._session.add(membership)
        await self._session.flush()
        return membership

    async def delete_member(self, membership: OrganizationMember) -> None:
        await self._session.delete(membership)
        await self._session.flush()

    async def search_all(
        self,
        *,
        search: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Organization], int]:
        filters = []
        if search:
            needle = f"%{search.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(Organization.name).like(needle),
                    func.lower(func.coalesce(Organization.domain, "")).like(needle),
                    func.lower(func.coalesce(Organization.website, "")).like(needle),
                    exists(
                        select(1).where(
                            TrustRegistryRecord.id == Organization.registry_record_id,
                            TrustRegistryRecord.deleted_at.is_(None),
                            or_(
                                func.lower(TrustRegistryRecord.legal_name).like(needle),
                                func.lower(
                                    func.coalesce(TrustRegistryRecord.display_name, "")
                                ).like(needle),
                            ),
                        )
                    ),
                    exists(
                        select(1).where(
                            TrustRegistryAlias.registry_record_id
                            == Organization.registry_record_id,
                            TrustRegistryAlias.deleted_at.is_(None),
                            func.lower(TrustRegistryAlias.alias_name).like(needle),
                        )
                    ),
                    exists(
                        select(1).where(
                            TrustRegistryDomain.registry_record_id
                            == Organization.registry_record_id,
                            TrustRegistryDomain.deleted_at.is_(None),
                            func.lower(TrustRegistryDomain.domain).like(needle),
                        )
                    ),
                    exists(
                        select(1).where(
                            TrustRegistryIdentifier.registry_record_id
                            == Organization.registry_record_id,
                            TrustRegistryIdentifier.deleted_at.is_(None),
                            or_(
                                func.lower(TrustRegistryIdentifier.identifier_value).like(needle),
                                func.lower(TrustRegistryIdentifier.identifier_type).like(needle),
                            ),
                        )
                    ),
                )
            )
        count = await self._session.scalar(
            select(func.count()).select_from(Organization).where(*filters)
        )
        rows = await self._session.execute(
            select(Organization)
            .options(joinedload(Organization.registry_record))
            .where(*filters)
            .order_by(Organization.name.asc(), Organization.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(rows.scalars().all()), int(count or 0)
