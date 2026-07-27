"""Admin-only projections for the shared Trust Registry."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import NotFoundError
from app.models.trust_registry_record import TrustRegistryRecord
from app.models.verification_request import VerificationRequest
from app.schemas.pagination import ListQueryParams, Page, filter_sort_paginate
from app.schemas.trust_registry import (
    TrustRegistryAdminActivityResponse,
    TrustRegistryAdminContactResponse,
    TrustRegistryAdminDetailResponse,
    TrustRegistryAdminMetricsResponse,
    TrustRegistryAdminRecordResponse,
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


class TrustRegistryAdminService:
    """Read-only Admin projections backed by the existing Registry and verification data."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._serializer = TrustRegistryService(session)

    async def list_records(self, params: ListQueryParams) -> Page[TrustRegistryAdminRecordResponse]:
        records = await self._load_records()
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
                "state",
                "aliases",
            ),
            status_field="state",
            allowed_sort_fields=(
                "created_at",
                "updated_at",
                "legal_name",
                "display_name",
                "registry_code",
            ),
            default_sort_by="created_at",
            force_page_envelope=True,
        )

    async def get_detail(self, registry_public_id: UUID) -> TrustRegistryAdminDetailResponse:
        record = next(
            (item for item in await self._load_records() if item.public_id == registry_public_id),
            None,
        )
        if record is None:
            raise NotFoundError("Trust Registry record not found")
        summary = self._to_summary(record)
        contacts = [
            self._to_contact(contact)
            for request in record.verification_requests
            for contact in request.verification_contacts
            if contact.superseded_at is None
        ]
        activity = [
            self._to_activity(event, request.subject_name)
            for request in record.verification_requests
            for event in request.events
        ]
        activity.sort(key=lambda item: item.at)
        return TrustRegistryAdminDetailResponse(
            **summary.model_dump(),
            contacts=contacts,
            activity=activity,
        )

    async def metrics(self) -> TrustRegistryAdminMetricsResponse:
        records = await self._load_records()
        summaries = [self._to_summary(record) for record in records]
        contacts = [
            contact
            for record in records
            for request in record.verification_requests
            for contact in request.verification_contacts
            if contact.superseded_at is None
        ]
        return TrustRegistryAdminMetricsResponse(
            total=len(summaries),
            verified=sum(item.state == "verified" for item in summaries),
            unverified=sum(item.state == "unverified" for item in summaries),
            duplicates=sum(item.state == "duplicate_review" for item in summaries),
            contacts_approved=sum(
                contact.review_status == VerificationContactReviewStatus.APPROVED
                for contact in contacts
            ),
            contacts_bounced=0,
        )

    async def _load_records(self) -> list[TrustRegistryRecord]:
        stmt = (
            select(TrustRegistryRecord)
            .options(
                selectinload(TrustRegistryRecord.domains),
                selectinload(TrustRegistryRecord.aliases),
                selectinload(TrustRegistryRecord.identifiers),
                selectinload(TrustRegistryRecord.capabilities),
                selectinload(TrustRegistryRecord.verification_requests)
                .selectinload(VerificationRequest.events),
                selectinload(TrustRegistryRecord.verification_requests)
                .selectinload(VerificationRequest.verification_contacts),
            )
            .where(TrustRegistryRecord.deleted_at.is_(None))
            .order_by(TrustRegistryRecord.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().unique().all())

    def _to_summary(self, record: TrustRegistryRecord) -> TrustRegistryAdminRecordResponse:
        base = self._serializer._to_record_response(record)
        metadata = dict(record.trust_metadata or {})
        possible_ids = self._possible_duplicate_ids(metadata)
        state = self._state(record, possible_ids)
        active_cases = sum(
            request.status not in _TERMINAL_STATUSES
            for request in record.verification_requests
        )
        return TrustRegistryAdminRecordResponse(
            **base.model_dump(),
            aliases=[alias.alias_name for alias in record.aliases if alias.deleted_at is None],
            domain=next(
                (
                    domain.domain
                    for domain in record.domains
                    if domain.deleted_at is None and domain.is_primary
                ),
                next(
                    (domain.domain for domain in record.domains if domain.deleted_at is None),
                    None,
                ),
            ),
            state=state,
            active_case_count=active_cases,
            total_verifications=len(record.verification_requests),
            possible_duplicate_ids=possible_ids,
            registry_flags=["possible_duplicate"] if state == "duplicate_review" else [],
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
        }.get(contact.review_status.value, "needs_review")
        return TrustRegistryAdminContactResponse(
            public_id=contact.public_id,
            name=contact.contact_name,
            role=contact.contact_role,
            email_masked=masked,
            state=state,
            added_by=str(contact.submitted_by_user_id),
            added_at=contact.created_at,
        )

    @staticmethod
    def _to_activity(event, subject_name: str) -> TrustRegistryAdminActivityResponse:  # noqa: ANN001
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
                f"{event.event_type.replace('_', ' ').capitalize()} for "
                f"{subject_name}{status_change}"
            ),
        )
