"""Synchronize workspace organizations with canonical Trust Registry records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError
from app.models.organization import Organization
from app.models.trust_registry_domain import TrustRegistryDomain
from app.models.trust_registry_record import TrustRegistryRecord
from app.models.verification_request import VerificationRequest
from app.repositories.trust_registry import (
    TrustRegistryAliasRepository,
    TrustRegistryDomainRepository,
    TrustRegistryRepository,
)
from app.schemas.trust_registry import TrustRegistryRecordCreateRequest
from app.services.trust_registry_service import TrustRegistryService
from app.trust_registry.enums import (
    TrustRegistryLifecycleStatus,
    TrustRegistryResolutionMethod,
    TrustRegistryResolutionState,
    TrustRegistrySourceType,
    TrustRegistryTrustStatus,
)

UNKNOWN_COUNTRY_CODE = "ZZ"


@dataclass(frozen=True)
class OrganizationRegistrySyncResult:
    """Explain how a workspace organization reached canonical Registry state."""

    organization_public_id: UUID
    registry_record_public_id: UUID
    action: str
    resolution_method: str
    request_links_synced: int


@dataclass(frozen=True)
class OrganizationRegistrySyncPlan:
    """Describe the idempotent sync action before mutating storage."""

    organization_public_id: UUID
    action: str
    resolution_method: str
    registry_record_public_id: UUID | None
    request_links_pending: int


class OrganizationRegistrySyncService:
    """Link workspace organizations and their requests to canonical Registry records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._records = TrustRegistryRepository(session)
        self._domains = TrustRegistryDomainRepository(session)
        self._aliases = TrustRegistryAliasRepository(session)
        self._registry = TrustRegistryService(session)

    async def sync_organization(
        self,
        organization: Organization,
        *,
        actor_user_id: UUID | None,
        commit: bool = False,
    ) -> OrganizationRegistrySyncResult:
        plan = await self.plan_sync_organization(organization)
        record: TrustRegistryRecord | None = None
        action = plan.action
        method = TrustRegistryResolutionMethod(plan.resolution_method)

        if action == "ambiguous_match":
            raise ConflictError(
                "Organization matches multiple Trust Registry records; "
                "manual resolution is required"
            )

        if organization.registry_record_id is not None:
            record = await self._records.get_by_id(organization.registry_record_id)

        if record is None:
            record, method, action = await self._match_or_create_record(
                organization,
                actor_user_id=actor_user_id,
            )
            self._link_organization(
                organization,
                record,
                actor_user_id=actor_user_id,
                method=method,
            )

        request_links_synced = await self._sync_related_requests(
            organization,
            record,
            actor_user_id=actor_user_id,
            method=method if action != "already_linked" else TrustRegistryResolutionMethod.MANUAL,
        )

        await self._session.flush()
        if commit:
            await self._session.commit()

        return OrganizationRegistrySyncResult(
            organization_public_id=organization.public_id,
            registry_record_public_id=record.public_id,
            action=action,
            resolution_method=method.value,
            request_links_synced=request_links_synced,
        )

    async def plan_sync_organization(
        self,
        organization: Organization,
    ) -> OrganizationRegistrySyncPlan:
        record_public_id: UUID | None = None
        action = "created_new_record"
        method = TrustRegistryResolutionMethod.CREATED_NEW
        pending_links = await self._count_pending_request_links(organization)

        if organization.registry_record_id is not None:
            record = await self._records.get_by_id(organization.registry_record_id)
            if record is not None:
                return OrganizationRegistrySyncPlan(
                    organization_public_id=organization.public_id,
                    action="already_linked",
                    resolution_method=TrustRegistryResolutionMethod.MANUAL.value,
                    registry_record_public_id=record.public_id,
                    request_links_pending=pending_links,
                )

        domain_matches = await self._find_domain_matches(organization)
        if len(domain_matches) > 1:
            return OrganizationRegistrySyncPlan(
                organization_public_id=organization.public_id,
                action="ambiguous_match",
                resolution_method=TrustRegistryResolutionMethod.EXACT_DOMAIN.value,
                registry_record_public_id=None,
                request_links_pending=pending_links,
            )
        if len(domain_matches) == 1:
            action = "linked_existing_domain"
            method = TrustRegistryResolutionMethod.EXACT_DOMAIN
            record_public_id = domain_matches[0].public_id
        else:
            name_matches = await self._find_name_matches(organization)
            if len(name_matches) > 1:
                return OrganizationRegistrySyncPlan(
                    organization_public_id=organization.public_id,
                    action="ambiguous_match",
                    resolution_method=TrustRegistryResolutionMethod.EXACT_NAME.value,
                    registry_record_public_id=None,
                    request_links_pending=pending_links,
                )
            if len(name_matches) == 1:
                action = "linked_existing_name"
                method = TrustRegistryResolutionMethod.EXACT_NAME
                record_public_id = name_matches[0].public_id

        return OrganizationRegistrySyncPlan(
            organization_public_id=organization.public_id,
            action=action,
            resolution_method=method.value,
            registry_record_public_id=record_public_id,
            request_links_pending=pending_links,
        )

    async def _match_or_create_record(
        self,
        organization: Organization,
        *,
        actor_user_id: UUID | None,
    ) -> tuple[TrustRegistryRecord, TrustRegistryResolutionMethod, str]:
        domain_matches = await self._find_domain_matches(organization)
        if len(domain_matches) > 1:
            raise ConflictError("Organization matches multiple Trust Registry records by domain")
        if len(domain_matches) == 1:
            return (
                domain_matches[0],
                TrustRegistryResolutionMethod.EXACT_DOMAIN,
                "linked_existing_domain",
            )

        name_matches = await self._find_name_matches(organization)
        if len(name_matches) > 1:
            raise ConflictError("Organization matches multiple Trust Registry records by name")
        if len(name_matches) == 1:
            return name_matches[0], TrustRegistryResolutionMethod.EXACT_NAME, "linked_existing_name"

        created = await self._registry.create_record(
            actor_user_id or organization.created_by_user_id,
            TrustRegistryRecordCreateRequest(
                legal_name=organization.name,
                display_name=organization.name,
                organization_type=self._organization_type_value(organization),
                country=UNKNOWN_COUNTRY_CODE,
                website=organization.website,
                lifecycle_status=TrustRegistryLifecycleStatus.DRAFT,
                trust_status=TrustRegistryTrustStatus.UNREVIEWED,
                registry_confidence_score=Decimal("0"),
                trust_metadata={
                    "source": "workspace_organization_sync",
                    "workspace_organization_public_id": str(organization.public_id),
                    "workspace_verification_state": self._verification_state_value(organization),
                    "workspace_domain": organization.domain,
                },
            ),
        )
        record = await self._records.get_by_public_id(created.public_id)
        if record is None:
            raise RuntimeError("Created Trust Registry record could not be reloaded")
        if organization.domain:
            self._session.add(
                TrustRegistryDomain(
                    registry_record_id=record.id,
                    domain=organization.domain.strip().lower(),
                    is_primary=True,
                    is_verified=False,
                    source_type=TrustRegistrySourceType.ORGANIZATION_SUBMISSION.value,
                    source_metadata={
                        "workspace_organization_public_id": str(organization.public_id),
                        "source": "workspace_organization_sync",
                    },
                )
            )
        return record, TrustRegistryResolutionMethod.CREATED_NEW, "created_new_record"

    async def _find_domain_matches(self, organization: Organization) -> list[TrustRegistryRecord]:
        if not organization.domain:
            return []
        return self._dedupe_active(
            item.registry_record
            for item in await self._domains.get_by_domain(organization.domain)
            if item.deleted_at is None
        )

    async def _find_name_matches(self, organization: Organization) -> list[TrustRegistryRecord]:
        normalized = organization.name.strip().lower()
        exact_records = [
            record
            for record in await self._records.search_by_name(organization.name)
            if record.legal_name.strip().lower() == normalized
            or (record.display_name or "").strip().lower() == normalized
        ]
        alias_records = [
            item.registry_record
            for item in await self._aliases.search(organization.name)
            if item.deleted_at is None
        ]
        return self._dedupe_active([*exact_records, *alias_records])

    def _link_organization(
        self,
        organization: Organization,
        record: TrustRegistryRecord,
        *,
        actor_user_id: UUID | None,
        method: TrustRegistryResolutionMethod,
    ) -> None:
        organization.registry_record_id = record.id
        organization.registry_record = record
        organization.registry_resolution_method = method.value
        organization.registry_resolution_confidence = self._resolution_confidence(method)
        organization.registry_resolution_metadata = {
            **dict(organization.registry_resolution_metadata or {}),
            "source": "workspace_organization_sync",
            "workspace_organization_public_id": str(organization.public_id),
        }
        organization.registry_resolved_at = datetime.now(tz=UTC)
        organization.registry_resolved_by_user_id = actor_user_id

    async def _sync_related_requests(
        self,
        organization: Organization,
        record: TrustRegistryRecord,
        *,
        actor_user_id: UUID | None,
        method: TrustRegistryResolutionMethod,
    ) -> int:
        rows = (
            (
                await self._session.execute(
                    select(VerificationRequest).where(
                        VerificationRequest.organization_id == organization.id,
                        VerificationRequest.registry_record_id.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for request in rows:
            request.registry_record_id = record.id
            request.registry_record = record
            request.registry_resolution_state = TrustRegistryResolutionState.RESOLVED.value
            request.registry_resolution_method = method.value
            request.registry_resolution_confidence = self._resolution_confidence(method)
            request.registry_resolution_metadata = {
                **dict(request.registry_resolution_metadata or {}),
                "source": "organization_registry_sync",
                "organization_public_id": str(organization.public_id),
            }
            request.registry_resolved_at = datetime.now(tz=UTC)
            request.registry_resolved_by_user_id = actor_user_id
        return len(rows)

    async def _count_pending_request_links(self, organization: Organization) -> int:
        return int(
            (
                await self._session.scalar(
                    select(func.count())
                    .where(
                        VerificationRequest.organization_id == organization.id,
                        VerificationRequest.registry_record_id.is_(None),
                    )
                )
            )
            or 0
        )

    @staticmethod
    def _dedupe_active(records) -> list[TrustRegistryRecord]:  # noqa: ANN001
        seen: set[UUID] = set()
        deduped: list[TrustRegistryRecord] = []
        for record in records:
            if record is None or record.deleted_at is not None or record.public_id in seen:
                continue
            seen.add(record.public_id)
            deduped.append(record)
        return deduped

    @staticmethod
    def _organization_type_value(organization: Organization) -> str:
        value = organization.organization_type
        return value.value if hasattr(value, "value") else str(value)

    @staticmethod
    def _verification_state_value(organization: Organization) -> str:
        value = organization.verification_state
        return value.value if hasattr(value, "value") else str(value)

    @staticmethod
    def _resolution_confidence(method: TrustRegistryResolutionMethod) -> float:
        if method == TrustRegistryResolutionMethod.EXACT_DOMAIN:
            return 100.0
        if method == TrustRegistryResolutionMethod.EXACT_NAME:
            return 90.0
        return 100.0
