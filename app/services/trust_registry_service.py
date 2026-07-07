"""Core Trust Registry management services."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError
from app.models.trust_registry_alias import TrustRegistryAlias
from app.models.trust_registry_capability import TrustRegistryCapability
from app.models.trust_registry_domain import TrustRegistryDomain
from app.models.trust_registry_identifier import TrustRegistryIdentifier
from app.models.trust_registry_relationship import TrustRegistryRelationship
from app.models.trust_registry_record import TrustRegistryRecord
from app.models.trust_registry_record_capability import TrustRegistryRecordCapability
from app.repositories.trust_registry import (
    TrustRegistryAliasRepository,
    TrustRegistryCapabilityRepository,
    TrustRegistryDomainRepository,
    TrustRegistryIdentifierRepository,
    TrustRegistryRecordCapabilityRepository,
    TrustRegistryRelationshipRepository,
    TrustRegistryRepository,
)
from app.schemas.pagination import ListQueryParams, Page, filter_sort_paginate
from app.schemas.trust_registry import (
    TrustRegistryAliasCreateRequest,
    TrustRegistryAliasResponse,
    TrustRegistryCapabilityCreateRequest,
    TrustRegistryCapabilityResponse,
    TrustRegistryDetailResponse,
    TrustRegistryDomainCreateRequest,
    TrustRegistryDomainResponse,
    TrustRegistryIdentifierCreateRequest,
    TrustRegistryIdentifierResponse,
    TrustRegistryRecordCapabilityCreateRequest,
    TrustRegistryRecordCapabilityResponse,
    TrustRegistryRecordCreateRequest,
    TrustRegistryRecordResponse,
    TrustRegistryRecordUpdateRequest,
    TrustRegistryRelationshipCreateRequest,
    TrustRegistryRelationshipResponse,
)


class TrustRegistryCodeService:
    """Immutable human-readable code generation for registry records."""

    def generate(self, *, public_id: UUID, organization_type: str) -> str:
        prefix = "".join(ch for ch in organization_type.upper() if ch.isalnum())[:3] or "REG"
        return f"KR-{prefix}-{public_id.hex[:8].upper()}"


class TrustRegistryService:
    """Create and maintain canonical Trust Registry records and linked metadata."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._records = TrustRegistryRepository(session)
        self._capabilities = TrustRegistryCapabilityRepository(session)
        self._domains = TrustRegistryDomainRepository(session)
        self._aliases = TrustRegistryAliasRepository(session)
        self._identifiers = TrustRegistryIdentifierRepository(session)
        self._record_capabilities = TrustRegistryRecordCapabilityRepository(session)
        self._relationships = TrustRegistryRelationshipRepository(session)
        self._code_service = TrustRegistryCodeService()

    async def create_record(
        self,
        actor_user_id: UUID,
        payload: TrustRegistryRecordCreateRequest,
    ) -> TrustRegistryDetailResponse:
        public_id = uuid.uuid4()
        record = TrustRegistryRecord(
            public_id=public_id,
            registry_code=self._code_service.generate(public_id=public_id, organization_type=payload.organization_type),
            legal_name=payload.legal_name,
            display_name=payload.display_name,
            organization_type=payload.organization_type,
            country=payload.country,
            state_province=payload.state_province,
            website=payload.website,
            lifecycle_status=payload.lifecycle_status.value,
            trust_status=payload.trust_status.value,
            registry_confidence_score=payload.registry_confidence_score,
            trust_metadata=payload.trust_metadata,
            created_by_user_id=actor_user_id,
            updated_by_user_id=actor_user_id,
        )
        await self._records.create(record)
        await self._commit_conflict_safe("Trust Registry record already exists")
        refreshed = await self._require_record(record.public_id)
        return self._to_detail_response(refreshed)

    async def update_record(
        self,
        actor_user_id: UUID,
        registry_public_id: UUID,
        payload: TrustRegistryRecordUpdateRequest,
    ) -> TrustRegistryDetailResponse:
        record = await self._require_record(registry_public_id)
        updates = payload.model_dump(exclude_unset=True)
        for key, value in updates.items():
            if value is None and key not in {"display_name", "state_province", "website"}:
                continue
            if hasattr(value, "value"):
                value = value.value
            setattr(record, key, value)
        record.updated_by_user_id = actor_user_id
        await self._commit_conflict_safe("Unable to update Trust Registry record")
        refreshed = await self._require_record(record.public_id)
        return self._to_detail_response(refreshed)

    async def get_detail(self, registry_public_id: UUID) -> TrustRegistryDetailResponse:
        return self._to_detail_response(await self._require_record(registry_public_id))

    async def list_records(
        self,
        params: ListQueryParams,
    ) -> Page[TrustRegistryRecordResponse] | list[TrustRegistryRecordResponse]:
        records = await self._records.search_by_name(params.search or "") if params.search else await self._records.list_all()
        responses = [self._to_record_response(record) for record in records]
        return filter_sort_paginate(
            responses,
            params=params,
            search_fields=("registry_code", "legal_name", "display_name", "organization_type", "country"),
            status_field="lifecycle_status",
            allowed_sort_fields=("created_at", "updated_at", "legal_name", "display_name", "registry_code"),
            default_sort_by="created_at",
            force_page_envelope=True,
        )

    async def create_capability(self, payload: TrustRegistryCapabilityCreateRequest) -> TrustRegistryCapabilityResponse:
        capability = TrustRegistryCapability(
            capability_key=payload.capability_key,
            display_name=payload.display_name,
            description=payload.description,
        )
        await self._capabilities.create(capability)
        await self._commit_conflict_safe("Trust Registry capability already exists")
        return self._to_capability_response(capability)

    async def add_domain(
        self,
        registry_public_id: UUID,
        payload: TrustRegistryDomainCreateRequest,
    ) -> TrustRegistryDomainResponse:
        record = await self._require_record(registry_public_id)
        domain = TrustRegistryDomain(
            registry_record_id=record.id,
            domain=payload.domain,
            is_primary=payload.is_primary,
            is_verified=payload.is_verified,
            source_type=payload.source_type.value,
            source_metadata=payload.source_metadata,
        )
        await self._domains.create(domain)
        await self._commit_conflict_safe("Trust Registry domain already exists")
        return self._to_domain_response(domain)

    async def add_alias(
        self,
        registry_public_id: UUID,
        payload: TrustRegistryAliasCreateRequest,
    ) -> TrustRegistryAliasResponse:
        record = await self._require_record(registry_public_id)
        alias = TrustRegistryAlias(
            registry_record_id=record.id,
            alias_name=payload.alias_name,
            alias_type=payload.alias_type.value,
            source_type=payload.source_type.value,
            source_metadata=payload.source_metadata,
        )
        await self._aliases.create(alias)
        await self._commit_conflict_safe("Trust Registry alias already exists")
        return self._to_alias_response(alias)

    async def add_identifier(
        self,
        registry_public_id: UUID,
        payload: TrustRegistryIdentifierCreateRequest,
    ) -> TrustRegistryIdentifierResponse:
        record = await self._require_record(registry_public_id)
        identifier = TrustRegistryIdentifier(
            registry_record_id=record.id,
            identifier_type=payload.identifier_type,
            identifier_value=payload.identifier_value,
            issuing_country=payload.issuing_country,
            issuing_authority=payload.issuing_authority,
            is_primary=payload.is_primary,
            is_verified=payload.is_verified,
            status=payload.status.value,
            source_type=payload.source_type.value,
            source_metadata=payload.source_metadata,
            metadata_payload=payload.metadata,
        )
        await self._identifiers.create(identifier)
        await self._commit_conflict_safe("Trust Registry identifier already exists")
        return self._to_identifier_response(identifier)

    async def add_capability_assignment(
        self,
        registry_public_id: UUID,
        payload: TrustRegistryRecordCapabilityCreateRequest,
    ) -> TrustRegistryRecordCapabilityResponse:
        record = await self._require_record(registry_public_id)
        capability = await self._capabilities.get_by_key(payload.capability_key)
        if capability is None:
            capability = TrustRegistryCapability(
                capability_key=payload.capability_key,
                display_name=payload.display_name or payload.capability_key.replace("_", " ").title(),
                description=payload.description,
            )
            await self._capabilities.create(capability)
        assignment = TrustRegistryRecordCapability(
            registry_record_id=record.id,
            capability_id=capability.id,
            status=payload.status.value,
            source_type=payload.source_type.value,
            source_metadata=payload.source_metadata,
        )
        await self._record_capabilities.create(assignment)
        await self._commit_conflict_safe("Trust Registry capability is already linked to this record")
        assignment.capability = capability
        return self._to_record_capability_response(assignment)

    async def add_relationship(
        self,
        registry_public_id: UUID,
        payload: TrustRegistryRelationshipCreateRequest,
    ) -> TrustRegistryRelationshipResponse:
        parent = await self._require_record(registry_public_id)
        child = await self._require_record(payload.child_registry_record_public_id)
        relationship = TrustRegistryRelationship(
            parent_registry_record_id=parent.id,
            child_registry_record_id=child.id,
            relationship_type=payload.relationship_type.value,
            status=payload.status.value,
            metadata_payload=payload.metadata,
        )
        await self._relationships.create(relationship)
        await self._commit_conflict_safe("Trust Registry relationship already exists")
        return self._to_relationship_response(relationship, parent.public_id, child.public_id)

    async def _require_record(self, registry_public_id: UUID) -> TrustRegistryRecord:
        record = await self._records.get_by_public_id(registry_public_id)
        if record is None:
            raise NotFoundError("Trust Registry record not found")
        return record

    async def _commit_conflict_safe(self, message: str) -> None:
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ConflictError(message) from exc

    def _to_record_response(self, record: TrustRegistryRecord) -> TrustRegistryRecordResponse:
        return TrustRegistryRecordResponse(
            public_id=record.public_id,
            registry_code=record.registry_code,
            legal_name=record.legal_name,
            display_name=record.display_name,
            organization_type=record.organization_type,
            country=record.country,
            state_province=record.state_province,
            website=record.website,
            lifecycle_status=record.lifecycle_status,
            trust_status=record.trust_status,
            registry_confidence_score=Decimal(str(record.registry_confidence_score)),
            trust_metadata=dict(record.trust_metadata or {}),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _to_detail_response(self, record: TrustRegistryRecord) -> TrustRegistryDetailResponse:
        return TrustRegistryDetailResponse(
            **self._to_record_response(record).model_dump(),
            domains=[self._to_domain_response(domain) for domain in record.domains if domain.deleted_at is None],
            aliases=[self._to_alias_response(alias) for alias in record.aliases if alias.deleted_at is None],
            identifiers=[
                self._to_identifier_response(identifier)
                for identifier in record.identifiers
                if identifier.deleted_at is None
            ],
            capabilities=[self._to_record_capability_response(capability) for capability in record.capabilities],
        )

    def _to_capability_response(self, capability: TrustRegistryCapability) -> TrustRegistryCapabilityResponse:
        return TrustRegistryCapabilityResponse(
            public_id=capability.public_id,
            capability_key=capability.capability_key,
            display_name=capability.display_name,
            description=capability.description,
            created_at=capability.created_at,
            updated_at=capability.updated_at,
        )

    def _to_record_capability_response(
        self,
        assignment: TrustRegistryRecordCapability,
    ) -> TrustRegistryRecordCapabilityResponse:
        return TrustRegistryRecordCapabilityResponse(
            public_id=assignment.public_id,
            capability=self._to_capability_response(assignment.capability),
            status=assignment.status,
            source_type=assignment.source_type,
            source_metadata=dict(assignment.source_metadata or {}),
            created_at=assignment.created_at,
            updated_at=assignment.updated_at,
        )

    def _to_domain_response(self, domain: TrustRegistryDomain) -> TrustRegistryDomainResponse:
        return TrustRegistryDomainResponse(
            public_id=domain.public_id,
            domain=domain.domain,
            is_primary=domain.is_primary,
            is_verified=domain.is_verified,
            source_type=domain.source_type,
            source_metadata=dict(domain.source_metadata or {}),
            created_at=domain.created_at,
            updated_at=domain.updated_at,
        )

    def _to_alias_response(self, alias: TrustRegistryAlias) -> TrustRegistryAliasResponse:
        return TrustRegistryAliasResponse(
            public_id=alias.public_id,
            alias_name=alias.alias_name,
            alias_type=alias.alias_type,
            source_type=alias.source_type,
            source_metadata=dict(alias.source_metadata or {}),
            created_at=alias.created_at,
            updated_at=alias.updated_at,
        )

    def _to_identifier_response(self, identifier: TrustRegistryIdentifier) -> TrustRegistryIdentifierResponse:
        return TrustRegistryIdentifierResponse(
            public_id=identifier.public_id,
            identifier_type=identifier.identifier_type,
            identifier_value=identifier.identifier_value,
            issuing_country=identifier.issuing_country,
            issuing_authority=identifier.issuing_authority,
            is_primary=identifier.is_primary,
            is_verified=identifier.is_verified,
            status=identifier.status,
            source_type=identifier.source_type,
            source_metadata=dict(identifier.source_metadata or {}),
            metadata=dict(identifier.metadata_payload or {}),
            created_at=identifier.created_at,
            updated_at=identifier.updated_at,
        )

    def _to_relationship_response(
        self,
        relationship: TrustRegistryRelationship,
        parent_public_id: UUID,
        child_public_id: UUID,
    ) -> TrustRegistryRelationshipResponse:
        return TrustRegistryRelationshipResponse(
            public_id=relationship.public_id,
            parent_registry_record_public_id=parent_public_id,
            child_registry_record_public_id=child_public_id,
            relationship_type=relationship.relationship_type,
            status=relationship.status,
            metadata=dict(relationship.metadata_payload or {}),
            created_at=relationship.created_at,
            updated_at=relationship.updated_at,
        )

