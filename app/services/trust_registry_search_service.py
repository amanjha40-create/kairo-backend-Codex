"""Search and exact lookup services for the Trust Registry."""

from __future__ import annotations

from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.trust_registry import (
    TrustRegistryAliasRepository,
    TrustRegistryDomainRepository,
    TrustRegistryIdentifierRepository,
    TrustRegistryRepository,
)
from app.schemas.pagination import ListQueryParams, Page, filter_sort_paginate
from app.schemas.trust_registry import (
    TrustRegistryLookupResponse,
    TrustRegistryRecordResponse,
)
from app.services.trust_registry_service import TrustRegistryService
from app.trust_registry.enums import TrustRegistryResolutionState


class TrustRegistrySearchService:
    """Lookup and ambiguity-detection helpers for Trust Registry consumers."""

    def __init__(self, session: AsyncSession) -> None:
        self._records = TrustRegistryRepository(session)
        self._domains = TrustRegistryDomainRepository(session)
        self._aliases = TrustRegistryAliasRepository(session)
        self._identifiers = TrustRegistryIdentifierRepository(session)
        self._serializer = TrustRegistryService(session)

    async def search(
        self,
        params: ListQueryParams,
    ) -> Page[TrustRegistryRecordResponse] | list[TrustRegistryRecordResponse]:
        records = await self._records.search_by_name(params.search or "")
        responses = [self._serializer._to_record_response(record) for record in records]
        return filter_sort_paginate(
            responses,
            params=params,
            search_fields=("registry_code", "legal_name", "display_name", "organization_type", "country"),
            status_field="lifecycle_status",
            allowed_sort_fields=("created_at", "updated_at", "legal_name", "display_name", "registry_code"),
            default_sort_by="created_at",
            force_page_envelope=True,
        )

    async def lookup_by_domain(self, domain: str) -> TrustRegistryLookupResponse:
        matches = [item.registry_record for item in await self._domains.get_by_domain(domain) if item.deleted_at is None]
        return self._to_lookup_response(self._dedupe(matches), "exact_domain")

    async def lookup_by_identifier(self, identifier_type: str, identifier_value: str) -> TrustRegistryLookupResponse:
        matches = [
            item.registry_record
            for item in await self._identifiers.get_by_type_and_value(identifier_type, identifier_value)
            if item.deleted_at is None
        ]
        return self._to_lookup_response(self._dedupe(matches), "exact_identifier")

    async def lookup_by_name(self, name: str) -> TrustRegistryLookupResponse:
        exact_records = [
            record
            for record in await self._records.search_by_name(name)
            if record.legal_name.strip().lower() == name.strip().lower()
            or (record.display_name or "").strip().lower() == name.strip().lower()
        ]
        alias_records = [item.registry_record for item in await self._aliases.search(name) if item.deleted_at is None]
        return self._to_lookup_response(self._dedupe([*exact_records, *alias_records]), "exact_name")

    def _to_lookup_response(self, matches: list, reason: str) -> TrustRegistryLookupResponse:
        state = (
            TrustRegistryResolutionState.UNRESOLVED
            if not matches
            else TrustRegistryResolutionState.RESOLVED
            if len(matches) == 1
            else TrustRegistryResolutionState.DEFERRED
        )
        return TrustRegistryLookupResponse(
            resolution_state=state,
            matches=[self._serializer._to_record_response(item) for item in matches],
            match_reason=reason,
        )

    def _dedupe(self, records: Iterable) -> list:
        seen = set()
        deduped = []
        for record in records:
            if record is None or record.deleted_at is not None or record.public_id in seen:
                continue
            seen.add(record.public_id)
            deduped.append(record)
        return deduped

