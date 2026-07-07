"""Resolution and merge operations for registry-linked entities."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError
from app.models.organization import Organization
from app.models.trust_registry_merge_history import TrustRegistryMergeHistory
from app.models.verification_request import VerificationRequest
from app.repositories.organization import OrganizationRepository
from app.repositories.trust_registry import TrustRegistryMergeHistoryRepository, TrustRegistryRepository
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
        organization.registry_resolution_confidence = float(payload.resolution_confidence) if payload.resolution_confidence is not None else None
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
        request.registry_resolution_confidence = float(payload.resolution_confidence) if payload.resolution_confidence is not None else None
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
                "resolution_confidence": float(payload.resolution_confidence) if payload.resolution_confidence is not None else None,
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
            await self._session.execute(select(Organization).where(Organization.registry_record_id == source.id))
        ).scalars().all()
        for organization in organizations:
            organization.registry_record_id = target.id

        requests = (
            await self._session.execute(select(VerificationRequest).where(VerificationRequest.registry_record_id == source.id))
        ).scalars().all()
        for request in requests:
            request.registry_record_id = target.id

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

    def _to_org_resolution_response(self, organization: Organization) -> TrustRegistryOrganizationResolutionResponse:
        return TrustRegistryOrganizationResolutionResponse(
            organization_public_id=organization.public_id,
            registry_record_public_id=organization.registry_record.public_id if organization.registry_record is not None else None,
            resolution_state=TrustRegistryResolutionState.RESOLVED if organization.registry_record_id is not None else TrustRegistryResolutionState.UNRESOLVED,
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
            registry_record_public_id=request.registry_record.public_id if request.registry_record is not None else None,
            resolution_state=TrustRegistryResolutionState(request.registry_resolution_state),
            resolution_method=request.registry_resolution_method,
            resolution_confidence=request.registry_resolution_confidence,
            resolution_metadata=dict(request.registry_resolution_metadata or {}),
        )
