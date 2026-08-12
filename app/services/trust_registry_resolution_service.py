"""Resolution and merge operations for registry-linked entities."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError
from app.models.organization import Organization
from app.models.trust_registry_merge_history import TrustRegistryMergeHistory
from app.models.trust_registry_record import TrustRegistryRecord
from app.models.verification_request import VerificationRequest
from app.repositories.organization import OrganizationRepository
from app.repositories.trust_registry import (
    TrustRegistryMergeHistoryRepository,
    TrustRegistryRepository,
)
from app.repositories.verification_request import VerificationRequestRepository
from app.schemas.trust_registry import (
    TrustRegistryCreateAndResolveRequest,
    TrustRegistryDeferResolutionRequest,
    TrustRegistryMergeRequest,
    TrustRegistryMergeResponse,
    TrustRegistryOrganizationResolutionResponse,
    TrustRegistryResolutionRequest,
    TrustRegistryVerificationRequestResolutionResponse,
)
from app.services.trust_registry_service import TrustRegistryService
from app.services.verification_request_workflow_service import VerificationRequestWorkflowService
from app.trust_registry.enums import TrustRegistryResolutionState
from app.verification_requests.enums import VerificationRequestEventSource


class TrustRegistryResolutionService:
    """Resolve organizations and verification requests to canonical registry records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._records = TrustRegistryRepository(session)
        self._organizations = OrganizationRepository(session)
        self._requests = VerificationRequestRepository(session)
        self._merges = TrustRegistryMergeHistoryRepository(session)
        self._registry_service = TrustRegistryService(session)
        self._workflow = VerificationRequestWorkflowService(self._requests)

    async def resolve_organization(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        payload: TrustRegistryResolutionRequest,
    ) -> TrustRegistryOrganizationResolutionResponse:
        organization = await self._organizations.get_by_public_id(org_public_id)
        if organization is None:
            raise NotFoundError("Organization not found")
        record = await self._records.get_by_public_id(payload.registry_record_public_id)
        if record is None:
            raise NotFoundError("Trust Registry record not found")

        organization.registry_record_id = record.id
        organization.registry_record = record
        organization.registry_resolution_method = payload.resolution_method.value
        organization.registry_resolution_confidence = (
            float(payload.resolution_confidence)
            if payload.resolution_confidence is not None
            else None
        )
        organization.registry_resolution_metadata = payload.resolution_metadata
        organization.registry_resolved_at = datetime.now(tz=UTC)
        organization.registry_resolved_by_user_id = actor_user_id
        await self._session.commit()
        return self._to_org_resolution_response(organization)

    async def resolve_verification_request(
        self,
        actor_user_id: UUID,
        verification_request_public_id: UUID,
        payload: TrustRegistryResolutionRequest,
    ) -> TrustRegistryVerificationRequestResolutionResponse:
        request = await self._require_request(verification_request_public_id)
        record = await self._require_record(payload.registry_record_public_id)

        request.registry_record_id = record.id
        request.registry_record = record
        request.registry_resolution_state = TrustRegistryResolutionState.RESOLVED.value
        request.registry_resolution_method = payload.resolution_method.value
        request.registry_resolution_confidence = (
            float(payload.resolution_confidence)
            if payload.resolution_confidence is not None
            else None
        )
        request.registry_resolution_metadata = payload.resolution_metadata
        request.registry_resolved_at = datetime.now(tz=UTC)
        request.registry_resolved_by_user_id = actor_user_id
        await self._workflow.record_action(
            request,
            actor_user_id=actor_user_id,
            event_type="verification_request_registry_resolved",
            event_source=VerificationRequestEventSource.ADMIN,
            metadata={
                "registry_record_public_id": str(record.public_id),
                "resolution_method": payload.resolution_method.value,
                "resolution_confidence": float(payload.resolution_confidence)
                if payload.resolution_confidence is not None
                else None,
            },
        )
        await self._session.commit()
        return self._to_request_resolution_response(request)

    async def create_record_and_resolve_verification_request(
        self,
        actor_user_id: UUID,
        verification_request_public_id: UUID,
        payload: TrustRegistryCreateAndResolveRequest,
    ) -> TrustRegistryVerificationRequestResolutionResponse:
        created = await self._registry_service.create_record(actor_user_id, payload.record)
        return await self.resolve_verification_request(
            actor_user_id,
            verification_request_public_id,
            TrustRegistryResolutionRequest(
                registry_record_public_id=created.public_id,
                resolution_method=payload.resolution_method,
                resolution_confidence=payload.resolution_confidence,
                resolution_metadata=payload.resolution_metadata,
            ),
        )

    async def defer_verification_request_resolution(
        self,
        actor_user_id: UUID,
        verification_request_public_id: UUID,
        payload: TrustRegistryDeferResolutionRequest,
    ) -> TrustRegistryVerificationRequestResolutionResponse:
        request = await self._require_request(verification_request_public_id)
        request.registry_resolution_state = TrustRegistryResolutionState.DEFERRED.value
        request.registry_resolution_method = None
        request.registry_resolution_confidence = None
        request.registry_resolution_metadata = payload.resolution_metadata
        request.registry_record_id = None
        request.registry_resolved_at = None
        request.registry_resolved_by_user_id = None
        await self._workflow.record_action(
            request,
            actor_user_id=actor_user_id,
            event_type="verification_request_registry_resolution_deferred",
            event_source=VerificationRequestEventSource.ADMIN,
            metadata=payload.resolution_metadata,
        )
        await self._session.commit()
        return self._to_request_resolution_response(request)

    async def merge_records(
        self,
        actor_user_id: UUID,
        source_registry_public_id: UUID,
        payload: TrustRegistryMergeRequest,
    ) -> TrustRegistryMergeResponse:
        source = await self._require_record(source_registry_public_id)
        target = await self._require_record(payload.target_registry_record_public_id)
        if source.id == target.id:
            raise ConflictError("A Trust Registry record cannot be merged into itself")

        organizations = (
            (
                await self._session.execute(
                    select(Organization).where(Organization.registry_record_id == source.id)
                )
            )
            .scalars()
            .all()
        )
        for organization in organizations:
            organization.registry_record_id = target.id

        requests = (
            (
                await self._session.execute(
                    select(VerificationRequest).where(
                        VerificationRequest.registry_record_id == source.id
                    )
                )
            )
            .scalars()
            .all()
        )
        for request in requests:
            request.registry_record_id = target.id

        self._merge_aliases(source, target, actor_user_id)
        self._merge_domains(source, target, actor_user_id)
        self._merge_identifiers(source, target, actor_user_id)
        await self._merge_capabilities(source, target)
        self._merge_relationships(source, target, actor_user_id)

        source.lifecycle_status = "archived"
        source.deleted_at = datetime.now(tz=UTC)
        source.deleted_by_user_id = actor_user_id
        source.updated_by_user_id = actor_user_id
        source.trust_metadata = {
            **dict(source.trust_metadata or {}),
            "merged_into_registry_public_id": str(target.public_id),
        }

        merge_event = TrustRegistryMergeHistory(
            source_registry_record_id=source.id,
            target_registry_record_id=target.id,
            merged_by_user_id=actor_user_id,
            merge_reason=payload.merge_reason,
            metadata_payload=payload.metadata,
        )
        await self._merges.create(merge_event)
        await self._session.commit()
        return TrustRegistryMergeResponse(
            public_id=merge_event.public_id,
            source_registry_record_public_id=source.public_id,
            target_registry_record_public_id=target.public_id,
            merge_reason=merge_event.merge_reason,
            metadata=dict(merge_event.metadata_payload or {}),
            created_at=merge_event.created_at,
        )

    def _merge_aliases(
        self,
        source: TrustRegistryRecord,
        target: TrustRegistryRecord,
        actor_user_id: UUID,
    ) -> None:
        target_keys = {
            alias.alias_name.strip().lower() for alias in target.aliases if alias.deleted_at is None
        }
        for alias in source.aliases:
            if alias.deleted_at is not None:
                continue
            key = alias.alias_name.strip().lower()
            if key in target_keys:
                alias.deleted_at = datetime.now(tz=UTC)
                alias.deleted_by_user_id = actor_user_id
                continue
            alias.registry_record_id = target.id
            target_keys.add(key)

    def _merge_domains(
        self,
        source: TrustRegistryRecord,
        target: TrustRegistryRecord,
        actor_user_id: UUID,
    ) -> None:
        target_keys = {
            domain.domain.strip().lower() for domain in target.domains if domain.deleted_at is None
        }
        has_primary = any(
            domain.deleted_at is None and domain.is_primary for domain in target.domains
        )
        for domain in source.domains:
            if domain.deleted_at is not None:
                continue
            key = domain.domain.strip().lower()
            if key in target_keys:
                domain.deleted_at = datetime.now(tz=UTC)
                domain.deleted_by_user_id = actor_user_id
                continue
            if has_primary and domain.is_primary:
                domain.is_primary = False
            elif domain.is_primary:
                has_primary = True
            domain.registry_record_id = target.id
            target_keys.add(key)

    def _merge_identifiers(
        self,
        source: TrustRegistryRecord,
        target: TrustRegistryRecord,
        actor_user_id: UUID,
    ) -> None:
        target_keys = {
            (
                identifier.identifier_type.strip().lower(),
                identifier.identifier_value.strip().lower(),
                (identifier.issuing_country or "").strip().upper(),
            )
            for identifier in target.identifiers
            if identifier.deleted_at is None
        }
        has_primary = any(
            identifier.deleted_at is None and identifier.is_primary
            for identifier in target.identifiers
        )
        for identifier in source.identifiers:
            if identifier.deleted_at is not None:
                continue
            key = (
                identifier.identifier_type.strip().lower(),
                identifier.identifier_value.strip().lower(),
                (identifier.issuing_country or "").strip().upper(),
            )
            if key in target_keys:
                identifier.deleted_at = datetime.now(tz=UTC)
                identifier.deleted_by_user_id = actor_user_id
                continue
            if has_primary and identifier.is_primary:
                identifier.is_primary = False
            elif identifier.is_primary:
                has_primary = True
            identifier.registry_record_id = target.id
            target_keys.add(key)

    async def _merge_capabilities(
        self,
        source: TrustRegistryRecord,
        target: TrustRegistryRecord,
    ) -> None:
        target_capability_ids = {capability.capability_id for capability in target.capabilities}
        for capability in source.capabilities:
            if capability.capability_id in target_capability_ids:
                await self._session.delete(capability)
                continue
            capability.registry_record_id = target.id
            target_capability_ids.add(capability.capability_id)

    def _merge_relationships(
        self,
        source: TrustRegistryRecord,
        target: TrustRegistryRecord,
        actor_user_id: UUID,
    ) -> None:
        active_relationships = [
            relationship
            for relationship in [*source.parent_relationships, *source.child_relationships]
            if relationship.deleted_at is None
        ]
        existing = {
            (
                relationship.parent_registry_record_id,
                relationship.child_registry_record_id,
                relationship.relationship_type,
            )
            for relationship in [*target.parent_relationships, *target.child_relationships]
            if relationship.deleted_at is None
        }
        for relationship in active_relationships:
            new_parent_id = (
                target.id
                if relationship.parent_registry_record_id == source.id
                else relationship.parent_registry_record_id
            )
            new_child_id = (
                target.id
                if relationship.child_registry_record_id == source.id
                else relationship.child_registry_record_id
            )
            key = (new_parent_id, new_child_id, relationship.relationship_type)
            if new_parent_id == new_child_id or key in existing:
                relationship.deleted_at = datetime.now(tz=UTC)
                relationship.deleted_by_user_id = actor_user_id
                continue
            relationship.parent_registry_record_id = new_parent_id
            relationship.child_registry_record_id = new_child_id
            existing.add(key)

    async def _require_record(self, registry_public_id: UUID):
        record = await self._records.get_by_public_id(registry_public_id)
        if record is None:
            raise NotFoundError("Trust Registry record not found")
        return record

    async def _require_request(self, verification_request_public_id: UUID):
        request = await self._requests.get_by_public_id(verification_request_public_id)
        if request is None:
            raise NotFoundError("Verification request not found")
        return request

    def _to_org_resolution_response(
        self, organization: Organization
    ) -> TrustRegistryOrganizationResolutionResponse:
        return TrustRegistryOrganizationResolutionResponse(
            organization_public_id=organization.public_id,
            registry_record_public_id=organization.registry_record.public_id
            if organization.registry_record is not None
            else None,
            resolution_state=TrustRegistryResolutionState.RESOLVED
            if organization.registry_record_id is not None
            else TrustRegistryResolutionState.UNRESOLVED,
            resolution_method=organization.registry_resolution_method,
            resolution_confidence=organization.registry_resolution_confidence,
            resolution_metadata=dict(organization.registry_resolution_metadata or {}),
        )

    def _to_request_resolution_response(
        self,
        request: VerificationRequest,
    ) -> TrustRegistryVerificationRequestResolutionResponse:
        return TrustRegistryVerificationRequestResolutionResponse(
            verification_request_public_id=request.public_id,
            registry_record_public_id=request.registry_record.public_id
            if request.registry_record is not None
            else None,
            resolution_state=TrustRegistryResolutionState(request.registry_resolution_state),
            resolution_method=request.registry_resolution_method,
            resolution_confidence=request.registry_resolution_confidence,
            resolution_metadata=dict(request.registry_resolution_metadata or {}),
        )
