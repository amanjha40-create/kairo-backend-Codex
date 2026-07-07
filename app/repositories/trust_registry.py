"""Repositories for Trust Registry infrastructure."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.models.trust_registry_alias import TrustRegistryAlias
from app.models.trust_registry_capability import TrustRegistryCapability
from app.models.trust_registry_domain import TrustRegistryDomain
from app.models.trust_registry_identifier import TrustRegistryIdentifier
from app.models.trust_registry_merge_history import TrustRegistryMergeHistory
from app.models.trust_registry_record import TrustRegistryRecord
from app.models.trust_registry_record_capability import TrustRegistryRecordCapability
from app.models.trust_registry_relationship import TrustRegistryRelationship


class TrustRegistryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, record: TrustRegistryRecord) -> TrustRegistryRecord:
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_by_public_id(self, public_id: UUID) -> TrustRegistryRecord | None:
        stmt = (
            select(TrustRegistryRecord)
            .options(
                selectinload(TrustRegistryRecord.domains),
                selectinload(TrustRegistryRecord.aliases),
                selectinload(TrustRegistryRecord.identifiers),
                selectinload(TrustRegistryRecord.capabilities).joinedload(TrustRegistryRecordCapability.capability),
            )
            .where(TrustRegistryRecord.public_id == public_id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(self, record_id: UUID) -> TrustRegistryRecord | None:
        stmt = select(TrustRegistryRecord).where(TrustRegistryRecord.id == record_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_registry_code(self, registry_code: str) -> TrustRegistryRecord | None:
        stmt = select(TrustRegistryRecord).where(TrustRegistryRecord.registry_code == registry_code)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def count(self) -> int:
        stmt = select(func.count()).select_from(TrustRegistryRecord)
        return int((await self._session.execute(stmt)).scalar_one())

    async def search_by_name(self, query: str) -> list[TrustRegistryRecord]:
        needle = f"%{query.strip().lower()}%"
        stmt = (
            select(TrustRegistryRecord)
            .where(
                or_(
                    func.lower(TrustRegistryRecord.legal_name).like(needle),
                    func.lower(TrustRegistryRecord.display_name).like(needle),
                )
            )
            .order_by(TrustRegistryRecord.legal_name.asc(), TrustRegistryRecord.created_at.desc())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())


class TrustRegistryCapabilityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, capability: TrustRegistryCapability) -> TrustRegistryCapability:
        self._session.add(capability)
        await self._session.flush()
        return capability

    async def get_by_public_id(self, public_id: UUID) -> TrustRegistryCapability | None:
        stmt = select(TrustRegistryCapability).where(TrustRegistryCapability.public_id == public_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_key(self, capability_key: str) -> TrustRegistryCapability | None:
        stmt = select(TrustRegistryCapability).where(TrustRegistryCapability.capability_key == capability_key)
        return (await self._session.execute(stmt)).scalar_one_or_none()


class TrustRegistryDomainRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, domain: TrustRegistryDomain) -> TrustRegistryDomain:
        self._session.add(domain)
        await self._session.flush()
        return domain

    async def get_by_public_id(self, public_id: UUID) -> TrustRegistryDomain | None:
        stmt = select(TrustRegistryDomain).where(TrustRegistryDomain.public_id == public_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_domain(self, domain: str) -> list[TrustRegistryDomain]:
        stmt = (
            select(TrustRegistryDomain)
            .options(joinedload(TrustRegistryDomain.registry_record))
            .where(func.lower(TrustRegistryDomain.domain) == domain.strip().lower())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())


class TrustRegistryAliasRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, alias: TrustRegistryAlias) -> TrustRegistryAlias:
        self._session.add(alias)
        await self._session.flush()
        return alias

    async def search(self, alias_name: str) -> list[TrustRegistryAlias]:
        stmt = (
            select(TrustRegistryAlias)
            .options(joinedload(TrustRegistryAlias.registry_record))
            .where(func.lower(TrustRegistryAlias.alias_name) == alias_name.strip().lower())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())


class TrustRegistryIdentifierRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, identifier: TrustRegistryIdentifier) -> TrustRegistryIdentifier:
        self._session.add(identifier)
        await self._session.flush()
        return identifier

    async def get_by_public_id(self, public_id: UUID) -> TrustRegistryIdentifier | None:
        stmt = select(TrustRegistryIdentifier).where(TrustRegistryIdentifier.public_id == public_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_type_and_value(
        self,
        identifier_type: str,
        identifier_value: str,
    ) -> list[TrustRegistryIdentifier]:
        stmt = (
            select(TrustRegistryIdentifier)
            .options(joinedload(TrustRegistryIdentifier.registry_record))
            .where(
                TrustRegistryIdentifier.identifier_type == identifier_type,
                TrustRegistryIdentifier.identifier_value == identifier_value,
            )
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())


class TrustRegistryRecordCapabilityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, assignment: TrustRegistryRecordCapability) -> TrustRegistryRecordCapability:
        self._session.add(assignment)
        await self._session.flush()
        return assignment


class TrustRegistryRelationshipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, relationship: TrustRegistryRelationship) -> TrustRegistryRelationship:
        self._session.add(relationship)
        await self._session.flush()
        return relationship


class TrustRegistryMergeHistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, merge_event: TrustRegistryMergeHistory) -> TrustRegistryMergeHistory:
        self._session.add(merge_event)
        await self._session.flush()
        return merge_event

