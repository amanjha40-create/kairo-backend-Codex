"""Admin-only projections for the shared Trust Registry."""

from __future__ import annotations

from collections import OrderedDict
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import NotFoundError
from app.models.organization import Organization
from app.models.trust_registry_merge_history import TrustRegistryMergeHistory
from app.models.trust_registry_record import TrustRegistryRecord
from app.models.trust_registry_record_capability import TrustRegistryRecordCapability
from app.models.trust_registry_relationship import TrustRegistryRelationship
from app.models.verification_request import VerificationRequest
from app.schemas.pagination import Page, filter_sort_paginate
from app.schemas.trust_registry import (
    AdminTrustRegistryListParams,
    TrustRegistryAdminActivityResponse,
    TrustRegistryAdminContactResponse,
    TrustRegistryAdminDetailResponse,
    TrustRegistryAdminMergeHistoryResponse,
    TrustRegistryAdminMetricsResponse,
    TrustRegistryAdminOrganizationLinkResponse,
    TrustRegistryAdminRecordResponse,
    TrustRegistryAdminRelationshipResponse,
    TrustRegistryAdminVerificationLinkResponse,
)
from app.services.trust_registry_service import TrustRegistryService
from app.verification_requests.enums import (
    VerificationContactReviewStatus,
    VerificationRequestStatus,
)

_TERMINAL_STATUSES = {
    VerificationRequestStatus.VERIFIED,
    VerificationRequestStatus.REJECTED,
    VerificationRequestStatus.CANCELLED,
    VerificationRequestStatus.EXPIRED,
}

_INSTITUTION_TYPES = {"educational_institution", "institution", "university", "college", "school"}
_EMPLOYER_TYPES = {
    "employer",
    "private_company",
    "public_company",
    "non_profit",
    "government",
    "platform",
    "certification_body",
}


class TrustRegistryAdminService:
    """Admin projections backed by canonical registry, organization, and verification data."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._serializer = TrustRegistryService(session)

    async def list_records(
        self, params: AdminTrustRegistryListParams
    ) -> Page[TrustRegistryAdminRecordResponse]:
        records = await self._load_summary_records()
        records = self._apply_record_filters(records, params)
        rows = [self._to_summary(record) for record in records]
        return filter_sort_paginate(
            rows,
            params=params,
            search_fields=(
                "registry_code",
                "legal_name",
                "display_name",
                "organization_type",
                "country",
                "domain",
                "aliases",
            ),
            status_field="state",
            allowed_sort_fields=(
                "created_at",
                "updated_at",
                "legal_name",
                "display_name",
                "registry_code",
                "organization_type",
                "linked_organization_count",
                "total_verifications",
            ),
            default_sort_by="created_at",
            force_page_envelope=True,
        )

    async def get_detail(self, registry_public_id: UUID) -> TrustRegistryAdminDetailResponse:
        record = await self._load_detail_record(registry_public_id)
        if record is None:
            raise NotFoundError("Trust Registry record not found")

        summary = self._to_summary(record)
        contacts = list(self._build_contacts(record).values())
        activity = self._build_activity(record)

        return TrustRegistryAdminDetailResponse(
            **summary.model_dump(),
            alias_items=[
                self._serializer._to_alias_response(alias)
                for alias in record.aliases
                if alias.deleted_at is None
            ],
            domains=[
                self._serializer._to_domain_response(domain)
                for domain in record.domains
                if domain.deleted_at is None
            ],
            identifiers=[
                self._serializer._to_identifier_response(identifier)
                for identifier in record.identifiers
                if identifier.deleted_at is None
            ],
            capabilities=[
                self._serializer._to_record_capability_response(capability)
                for capability in record.capabilities
            ],
            relationships=self._build_relationships(record),
            linked_organizations=[
                self._to_linked_organization(org) for org in record.organizations
            ],
            verification_requests=[
                self._to_verification_link(request)
                for request in sorted(
                    record.verification_requests, key=lambda item: item.updated_at, reverse=True
                )
            ],
            merge_history=self._build_merge_history(record),
            contacts=contacts,
            activity=activity,
        )

    async def metrics(self) -> TrustRegistryAdminMetricsResponse:
        records = await self._load_summary_records()
        summaries = [self._to_summary(record) for record in records]
        contacts = [
            contact
            for record in records
            for request in record.verification_requests
            for contact in request.verification_contacts
            if contact.superseded_at is None
        ]
        unresolved_organizations = int(
            (
                await self._session.scalar(
                    select(func.count())
                    .select_from(Organization)
                    .where(Organization.registry_record_id.is_(None))
                )
            )
            or 0
        )
        linked_organizations = sum(len(record.organizations) for record in records)
        return TrustRegistryAdminMetricsResponse(
            total=len(summaries),
            employers=sum(self._is_employer_type(item.organization_type) for item in summaries),
            institutions=sum(
                self._is_institution_type(item.organization_type) for item in summaries
            ),
            verified=sum(item.state == "verified" for item in summaries),
            unverified=sum(item.state == "unverified" for item in summaries),
            duplicates=sum(item.state == "duplicate_review" for item in summaries),
            unresolved_organizations=unresolved_organizations,
            linked_organizations=linked_organizations,
            contacts_approved=sum(
                self._review_status_value(contact.review_status)
                == VerificationContactReviewStatus.APPROVED.value
                for contact in contacts
            ),
            contacts_bounced=0,
        )

    async def _load_summary_records(self) -> list[TrustRegistryRecord]:
        stmt = (
            select(TrustRegistryRecord)
            .options(
                selectinload(TrustRegistryRecord.domains),
                selectinload(TrustRegistryRecord.aliases),
                selectinload(TrustRegistryRecord.identifiers),
                selectinload(TrustRegistryRecord.capabilities).selectinload(
                    TrustRegistryRecordCapability.capability
                ),
                selectinload(TrustRegistryRecord.parent_relationships),
                selectinload(TrustRegistryRecord.child_relationships),
                selectinload(TrustRegistryRecord.organizations),
                selectinload(TrustRegistryRecord.verification_requests).selectinload(
                    VerificationRequest.verification_contacts
                ),
            )
            .where(TrustRegistryRecord.deleted_at.is_(None))
            .order_by(TrustRegistryRecord.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().unique().all())

    async def _load_detail_record(self, registry_public_id: UUID) -> TrustRegistryRecord | None:
        stmt = (
            select(TrustRegistryRecord)
            .options(
                selectinload(TrustRegistryRecord.domains),
                selectinload(TrustRegistryRecord.aliases),
                selectinload(TrustRegistryRecord.identifiers),
                selectinload(TrustRegistryRecord.capabilities).selectinload(
                    TrustRegistryRecordCapability.capability
                ),
                selectinload(TrustRegistryRecord.parent_relationships).selectinload(
                    TrustRegistryRelationship.child_registry_record
                ),
                selectinload(TrustRegistryRecord.child_relationships).selectinload(
                    TrustRegistryRelationship.parent_registry_record
                ),
                selectinload(TrustRegistryRecord.organizations).selectinload(Organization.members),
                selectinload(TrustRegistryRecord.verification_requests).selectinload(
                    VerificationRequest.events
                ),
                selectinload(TrustRegistryRecord.verification_requests).selectinload(
                    VerificationRequest.verification_contacts
                ),
                selectinload(TrustRegistryRecord.verification_requests).selectinload(
                    VerificationRequest.organization
                ),
                selectinload(TrustRegistryRecord.source_merge_history).selectinload(
                    TrustRegistryMergeHistory.target_registry_record
                ),
                selectinload(TrustRegistryRecord.target_merge_history).selectinload(
                    TrustRegistryMergeHistory.source_registry_record
                ),
            )
            .where(
                TrustRegistryRecord.public_id == registry_public_id,
                TrustRegistryRecord.deleted_at.is_(None),
            )
        )
        return (await self._session.execute(stmt)).scalars().unique().one_or_none()

    def _apply_record_filters(
        self,
        records: list[TrustRegistryRecord],
        params: AdminTrustRegistryListParams,
    ) -> list[TrustRegistryRecord]:
        filtered = records
        if params.organization_type:
            accepted = {
                value.strip().lower()
                for value in params.organization_type.split(",")
                if value.strip()
            }
            filtered = [
                record for record in filtered if record.organization_type.lower() in accepted
            ]
        if params.lifecycle_status:
            accepted = {
                value.strip().lower()
                for value in params.lifecycle_status.split(",")
                if value.strip()
            }
            filtered = [
                record for record in filtered if record.lifecycle_status.lower() in accepted
            ]
        if params.trust_status:
            accepted = {
                value.strip().lower() for value in params.trust_status.split(",") if value.strip()
            }
            filtered = [record for record in filtered if record.trust_status.lower() in accepted]
        if params.verification_state:
            accepted = {
                value.strip().lower()
                for value in params.verification_state.split(",")
                if value.strip()
            }
            filtered = [
                record
                for record in filtered
                if any(
                    self._verification_state_value(org) in accepted for org in record.organizations
                )
            ]
        return filtered

    def _to_summary(self, record: TrustRegistryRecord) -> TrustRegistryAdminRecordResponse:
        base = self._serializer._to_record_response(record)
        metadata = dict(record.trust_metadata or {})
        possible_ids = self._possible_duplicate_ids(metadata)
        state = self._state(record, possible_ids)
        active_cases = sum(
            request.status not in _TERMINAL_STATUSES for request in record.verification_requests
        )
        aliases = [alias.alias_name for alias in record.aliases if alias.deleted_at is None]
        identifiers_count = sum(identifier.deleted_at is None for identifier in record.identifiers)
        relationship_count = sum(
            relationship.deleted_at is None
            for relationship in [*record.parent_relationships, *record.child_relationships]
        )
        capabilities_count = len(record.capabilities)
        linked_organization_count = len(record.organizations)
        return TrustRegistryAdminRecordResponse(
            **base.model_dump(),
            aliases=aliases,
            domain=self._primary_domain(record),
            state=state,
            active_case_count=active_cases,
            total_verifications=len(record.verification_requests),
            aliases_count=len(aliases),
            identifiers_count=identifiers_count,
            relationship_count=relationship_count,
            capabilities_count=capabilities_count,
            linked_organization_count=linked_organization_count,
            possible_duplicate_ids=possible_ids,
            registry_flags=["possible_duplicate"] if state == "duplicate_review" else [],
        )

    def _build_contacts(
        self,
        record: TrustRegistryRecord,
    ) -> OrderedDict[UUID, TrustRegistryAdminContactResponse]:
        contacts: OrderedDict[UUID, TrustRegistryAdminContactResponse] = OrderedDict()
        for request in sorted(
            record.verification_requests, key=lambda item: item.updated_at, reverse=True
        ):
            for contact in request.verification_contacts:
                if contact.superseded_at is not None or contact.public_id in contacts:
                    continue
                contacts[contact.public_id] = self._to_contact(contact)
        return contacts

    def _build_relationships(
        self,
        record: TrustRegistryRecord,
    ) -> list[TrustRegistryAdminRelationshipResponse]:
        items: list[TrustRegistryAdminRelationshipResponse] = []
        for relationship in record.parent_relationships:
            if relationship.deleted_at is not None or relationship.child_registry_record is None:
                continue
            items.append(
                TrustRegistryAdminRelationshipResponse(
                    public_id=relationship.public_id,
                    direction="parent",
                    relationship_type=relationship.relationship_type,
                    status=relationship.status,
                    related_registry_record_public_id=relationship.child_registry_record.public_id,
                    related_registry_record_name=self._registry_name(
                        relationship.child_registry_record
                    ),
                    metadata=dict(relationship.metadata_payload or {}),
                    created_at=relationship.created_at,
                    updated_at=relationship.updated_at,
                )
            )
        for relationship in record.child_relationships:
            if relationship.deleted_at is not None or relationship.parent_registry_record is None:
                continue
            items.append(
                TrustRegistryAdminRelationshipResponse(
                    public_id=relationship.public_id,
                    direction="child",
                    relationship_type=relationship.relationship_type,
                    status=relationship.status,
                    related_registry_record_public_id=relationship.parent_registry_record.public_id,
                    related_registry_record_name=self._registry_name(
                        relationship.parent_registry_record
                    ),
                    metadata=dict(relationship.metadata_payload or {}),
                    created_at=relationship.created_at,
                    updated_at=relationship.updated_at,
                )
            )
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items

    def _build_merge_history(
        self,
        record: TrustRegistryRecord,
    ) -> list[TrustRegistryAdminMergeHistoryResponse]:
        events: list[TrustRegistryAdminMergeHistoryResponse] = []
        for merge in record.source_merge_history:
            if merge.target_registry_record is None:
                continue
            events.append(
                TrustRegistryAdminMergeHistoryResponse(
                    public_id=merge.public_id,
                    direction="merged_into",
                    other_registry_record_public_id=merge.target_registry_record.public_id,
                    other_registry_record_name=self._registry_name(merge.target_registry_record),
                    merged_by_user_id=merge.merged_by_user_id,
                    merge_reason=merge.merge_reason,
                    metadata=dict(merge.metadata_payload or {}),
                    created_at=merge.created_at,
                )
            )
        for merge in record.target_merge_history:
            if merge.source_registry_record is None:
                continue
            events.append(
                TrustRegistryAdminMergeHistoryResponse(
                    public_id=merge.public_id,
                    direction="absorbed",
                    other_registry_record_public_id=merge.source_registry_record.public_id,
                    other_registry_record_name=self._registry_name(merge.source_registry_record),
                    merged_by_user_id=merge.merged_by_user_id,
                    merge_reason=merge.merge_reason,
                    metadata=dict(merge.metadata_payload or {}),
                    created_at=merge.created_at,
                )
            )
        events.sort(key=lambda item: item.created_at, reverse=True)
        return events

    def _build_activity(
        self,
        record: TrustRegistryRecord,
    ) -> list[TrustRegistryAdminActivityResponse]:
        items: list[TrustRegistryAdminActivityResponse] = [
            TrustRegistryAdminActivityResponse(
                public_id=record.public_id,
                at=record.created_at,
                kind="registry_record_created",
                actor=str(record.created_by_user_id or "system"),
                description=f"Registry record created for {self._registry_name(record)}.",
            )
        ]
        if record.updated_at != record.created_at:
            items.append(
                TrustRegistryAdminActivityResponse(
                    public_id=record.public_id,
                    at=record.updated_at,
                    kind="registry_record_updated",
                    actor=str(record.updated_by_user_id or "system"),
                    description=f"Registry record updated for {self._registry_name(record)}.",
                )
            )

        items.extend(
            TrustRegistryAdminActivityResponse(
                public_id=alias.public_id,
                at=alias.created_at,
                kind="registry_alias_added",
                actor=alias.source_type,
                description=f"Alias added: {alias.alias_name}.",
            )
            for alias in record.aliases
            if alias.deleted_at is None
        )
        items.extend(
            TrustRegistryAdminActivityResponse(
                public_id=domain.public_id,
                at=domain.created_at,
                kind="registry_domain_added",
                actor=domain.source_type,
                description=f"Domain added: {domain.domain}.",
            )
            for domain in record.domains
            if domain.deleted_at is None
        )
        items.extend(
            TrustRegistryAdminActivityResponse(
                public_id=identifier.public_id,
                at=identifier.created_at,
                kind="registry_identifier_added",
                actor=identifier.source_type,
                description=(
                    f"Identifier added: {identifier.identifier_type}:{identifier.identifier_value}."
                ),
            )
            for identifier in record.identifiers
            if identifier.deleted_at is None
        )
        items.extend(
            TrustRegistryAdminActivityResponse(
                public_id=capability.public_id,
                at=capability.created_at,
                kind="registry_capability_added",
                actor=capability.source_type,
                description=f"Capability added: {self._capability_label(capability)}.",
            )
            for capability in record.capabilities
            if capability.capability is not None
        )
        items.extend(
            TrustRegistryAdminActivityResponse(
                public_id=merge.public_id,
                at=merge.created_at,
                kind="registry_merged",
                actor=str(merge.merged_by_user_id or "system"),
                description=(
                    f"Merged {self._registry_name(record)} "
                    f"{'into' if merge.source_registry_record_id == record.id else 'from'} "
                    f"{self._other_merge_name(record, merge)}."
                ),
            )
            for merge in [*record.source_merge_history, *record.target_merge_history]
        )
        items.extend(
            self._to_activity(event, request.public_id)
            for request in record.verification_requests
            for event in request.events
        )
        items.sort(key=lambda item: item.at, reverse=True)
        return items

    def _to_linked_organization(
        self,
        organization: Organization,
    ) -> TrustRegistryAdminOrganizationLinkResponse:
        active_members = sum(member.suspended_at is None for member in organization.members)
        return TrustRegistryAdminOrganizationLinkResponse(
            public_id=organization.public_id,
            name=organization.name,
            organization_type=self._normalize_organization_type(organization.organization_type),
            verification_state=self._verification_state_value(organization),
            registry_resolution_status="resolved"
            if organization.registry_record_id
            else "unresolved",
            verification_capabilities=list(organization.verification_capabilities or []),
            domain=organization.domain,
            setup_completed_at=organization.setup_completed_at,
            suspended_at=organization.suspended_at,
            suspension_reason=organization.suspension_reason,
            member_count=active_members,
            created_at=organization.created_at,
            updated_at=organization.updated_at,
        )

    def _to_verification_link(
        self,
        request: VerificationRequest,
    ) -> TrustRegistryAdminVerificationLinkResponse:
        return TrustRegistryAdminVerificationLinkResponse(
            public_id=request.public_id,
            request_type=request.request_type.value
            if hasattr(request.request_type, "value")
            else str(request.request_type),
            status=request.status.value
            if hasattr(request.status, "value")
            else str(request.status),
            organization_public_id=request.organization.public_id
            if request.organization is not None
            else None,
            organization_name=request.organization.name
            if request.organization is not None
            else request.target_organization_name,
            linked_record_public_id=None,
            created_at=request.created_at,
            updated_at=request.updated_at,
        )

    @staticmethod
    def _possible_duplicate_ids(metadata: dict) -> list[UUID]:
        values = metadata.get("possible_duplicate_ids", [])
        result: list[UUID] = []
        if isinstance(values, list):
            for value in values:
                try:
                    result.append(UUID(str(value)))
                except (TypeError, ValueError):
                    continue
        return result

    @staticmethod
    def _state(record: TrustRegistryRecord, possible_ids: list[UUID]) -> str:
        metadata = dict(record.trust_metadata or {})
        if record.lifecycle_status == "archived":
            return "deprecated"
        if possible_ids or metadata.get("duplicate_review") is True:
            return "duplicate_review"
        if record.trust_status == "trusted":
            return "verified"
        return "unverified"

    @staticmethod
    def _to_contact(contact) -> TrustRegistryAdminContactResponse:  # noqa: ANN001
        email = contact.contact_email
        local, _, domain = email.partition("@")
        masked = f"{local[:1]}{'•' * max(2, len(local) - 1)}@{domain}" if domain else "[redacted]"
        state = {
            VerificationContactReviewStatus.APPROVED.value: "approved",
            VerificationContactReviewStatus.PENDING.value: "unverified",
            VerificationContactReviewStatus.CHANGES_REQUESTED.value: "needs_review",
        }.get(
            TrustRegistryAdminService._review_status_value(contact.review_status),
            "needs_review",
        )
        return TrustRegistryAdminContactResponse(
            public_id=contact.public_id,
            name=contact.contact_name,
            role=contact.contact_role,
            email_masked=masked,
            state=state,
            added_by=str(contact.submitted_by_user_id),
            added_at=contact.created_at,
            last_successful_use=getattr(contact, "last_successful_use_at", None),
        )

    @staticmethod
    def _review_status_value(review_status: object) -> str:
        return review_status.value if hasattr(review_status, "value") else str(review_status)

    @staticmethod
    def _to_activity(event, request_public_id: UUID) -> TrustRegistryAdminActivityResponse:  # noqa: ANN001
        status_change = ""
        if event.previous_status or event.new_status:
            status_change = (
                f" ({event.previous_status or 'created'} → {event.new_status or 'updated'})"
            )
        return TrustRegistryAdminActivityResponse(
            public_id=event.public_id,
            at=event.created_at,
            kind=event.event_type,
            actor=str(event.actor_user_id or "system"),
            description=(
                f"{event.event_type.replace('_', ' ').capitalize()} "
                f"on verification {request_public_id}{status_change}"
            ),
        )

    @staticmethod
    def _registry_name(record: TrustRegistryRecord) -> str:
        return (record.display_name or record.legal_name).strip()

    @staticmethod
    def _primary_domain(record: TrustRegistryRecord) -> str | None:
        for domain in record.domains:
            if domain.deleted_at is None and domain.is_primary:
                return domain.domain
        for domain in record.domains:
            if domain.deleted_at is None:
                return domain.domain
        return None

    @staticmethod
    def _normalize_organization_type(value: object) -> str:
        return value.value if hasattr(value, "value") else str(value)

    def _verification_state_value(self, organization: Organization) -> str:
        return (
            organization.verification_state.value
            if hasattr(organization.verification_state, "value")
            else str(organization.verification_state)
        )

    @staticmethod
    def _capability_label(capability: TrustRegistryRecordCapability) -> str:
        if capability.capability is None:
            return "Unknown capability"
        return (
            capability.capability.display_name
            or capability.capability.capability_key
        )

    @staticmethod
    def _other_merge_name(record: TrustRegistryRecord, merge: TrustRegistryMergeHistory) -> str:
        if (
            merge.source_registry_record_id == record.id
            and merge.target_registry_record is not None
        ):
            return (
                merge.target_registry_record.display_name or merge.target_registry_record.legal_name
            ).strip()
        if (
            merge.target_registry_record_id == record.id
            and merge.source_registry_record is not None
        ):
            return (
                merge.source_registry_record.display_name or merge.source_registry_record.legal_name
            ).strip()
        return "another registry record"

    @staticmethod
    def _is_employer_type(value: str) -> bool:
        normalized = value.strip().lower()
        return normalized in _EMPLOYER_TYPES or "company" in normalized or "employer" in normalized

    @staticmethod
    def _is_institution_type(value: str) -> bool:
        normalized = value.strip().lower()
        return normalized in _INSTITUTION_TYPES or any(
            token in normalized
            for token in ("institution", "university", "college", "school", "education")
        )
