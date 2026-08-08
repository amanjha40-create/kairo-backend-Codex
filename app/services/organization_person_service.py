"""Organization People Registry service layer."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.exceptions import ForbiddenError, NotFoundError
from app.infrastructure.s3.presign import generate_presigned_get_url
from app.models.employment import Employment
from app.models.organization_person import OrganizationPerson
from app.models.organization_person_identifier import OrganizationPersonIdentifier
from app.models.organization_person_note import OrganizationPersonNote
from app.models.organization_person_passport_access import OrganizationPersonPassportAccess
from app.models.trust_invitation import TrustInvitation
from app.models.verification_request import VerificationRequest
from app.organization_people.enums import (
    OrganizationPersonIdentifierType,
    OrganizationPersonInvitationStatusSummary,
    OrganizationPersonPassportAccessState,
    OrganizationPersonPassportStatusSummary,
    OrganizationPersonRelationship,
    OrganizationPersonTrustState,
    OrganizationPersonVerificationStatusSummary,
)
from app.repositories.employment import EmploymentRepository
from app.repositories.employment_document import EmploymentDocumentRepository
from app.repositories.organization import OrganizationRepository
from app.repositories.organization_person import OrganizationPersonRepository
from app.repositories.user import UserRepository
from app.repositories.user_document import UserDocumentRepository
from app.schemas.organization_person import (
    OrganizationPeopleDirectorySummary,
    OrganizationPeopleListQueryParams,
    OrganizationPeopleListResponse,
    OrganizationPersonActivityResponse,
    OrganizationPersonDetailResponse,
    OrganizationPersonEmploymentVerificationResponse,
    OrganizationPersonListItemResponse,
    OrganizationPersonNoteRequest,
    OrganizationPersonNoteResponse,
    OrganizationPersonPassportClaimResponse,
    OrganizationPersonPassportPreviewResponse,
    OrganizationPersonRelationshipSummaryResponse,
    OrganizationPersonSharedEvidenceResponse,
    OrganizationPersonSummaryCounts,
    OrganizationPersonSummaryResponse,
    OrganizationPersonVerificationSummaryResponse,
)
from app.schemas.pagination import Page, filter_sort_paginate
from app.schemas.passport_share import PassportSharePermissions
from app.services.public_passport_service import PublicPassportService
from app.trust_invitations.enums import TrustInvitationStatus
from app.verification_requests.enums import VerificationRequestStatus, VerificationRequestType

_PHONE_CLEAN_RE = re.compile(r"[^\d+]")

_INVITATION_STATUS_MAP: dict[TrustInvitationStatus, OrganizationPersonInvitationStatusSummary] = {
    TrustInvitationStatus.DRAFT: OrganizationPersonInvitationStatusSummary.DRAFT,
    TrustInvitationStatus.PENDING: OrganizationPersonInvitationStatusSummary.SENT,
    TrustInvitationStatus.ACCEPTED: OrganizationPersonInvitationStatusSummary.ACCEPTED,
    TrustInvitationStatus.CANCELLED: OrganizationPersonInvitationStatusSummary.CANCELLED,
    TrustInvitationStatus.EXPIRED: OrganizationPersonInvitationStatusSummary.EXPIRED,
}

_VERIFICATION_STATUS_MAP: dict[VerificationRequestStatus, OrganizationPersonVerificationStatusSummary] = {
    VerificationRequestStatus.DRAFT: OrganizationPersonVerificationStatusSummary.NOT_STARTED,
    VerificationRequestStatus.PENDING_SUBJECT_ACCEPTANCE: OrganizationPersonVerificationStatusSummary.WAITING_FOR_CANDIDATE,
    VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION: OrganizationPersonVerificationStatusSummary.WAITING_FOR_CANDIDATE,
    VerificationRequestStatus.PENDING_ADMIN_REVIEW: OrganizationPersonVerificationStatusSummary.IN_VERIFICATION,
    VerificationRequestStatus.AWAITING_SUBJECT_CORRECTIONS: OrganizationPersonVerificationStatusSummary.CLARIFICATION_REQUIRED,
    VerificationRequestStatus.PENDING_ADMIN_RE_REVIEW: OrganizationPersonVerificationStatusSummary.IN_VERIFICATION,
    VerificationRequestStatus.APPROVED_FOR_ORGANIZATION_VERIFICATION: OrganizationPersonVerificationStatusSummary.IN_VERIFICATION,
    VerificationRequestStatus.PENDING_ORGANIZATION_RESOLUTION: OrganizationPersonVerificationStatusSummary.IN_VERIFICATION,
    VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE: OrganizationPersonVerificationStatusSummary.IN_VERIFICATION,
    VerificationRequestStatus.IN_PROGRESS: OrganizationPersonVerificationStatusSummary.IN_VERIFICATION,
    VerificationRequestStatus.AWAITING_INFORMATION: OrganizationPersonVerificationStatusSummary.CLARIFICATION_REQUIRED,
    VerificationRequestStatus.PENDING_ADMIN_QUALITY_REVIEW: OrganizationPersonVerificationStatusSummary.IN_VERIFICATION,
    VerificationRequestStatus.VERIFIED: OrganizationPersonVerificationStatusSummary.COMPLETED,
    VerificationRequestStatus.REJECTED: OrganizationPersonVerificationStatusSummary.UNABLE_TO_VERIFY,
    VerificationRequestStatus.UNABLE_TO_VERIFY: OrganizationPersonVerificationStatusSummary.UNABLE_TO_VERIFY,
    VerificationRequestStatus.CANCELLED: OrganizationPersonVerificationStatusSummary.CANCELLED,
    VerificationRequestStatus.EXPIRED: OrganizationPersonVerificationStatusSummary.UNABLE_TO_VERIFY,
}

_ACTIVE_VERIFICATION_SUMMARIES = {
    OrganizationPersonVerificationStatusSummary.WAITING_FOR_CANDIDATE,
    OrganizationPersonVerificationStatusSummary.IN_VERIFICATION,
    OrganizationPersonVerificationStatusSummary.CLARIFICATION_REQUIRED,
}


class OrganizationPersonService:
    """Canonical organization-scoped people registry service."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        repo: OrganizationPersonRepository | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._repo = repo or OrganizationPersonRepository(session)
        self._organizations = OrganizationRepository(session)
        self._users = UserRepository(session)
        self._employments = EmploymentRepository(session)
        self._employment_documents = EmploymentDocumentRepository(session)
        self._user_documents = UserDocumentRepository(session)
        self._public_passport = PublicPassportService(session, settings)

    async def list_for_organization(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        params: OrganizationPeopleListQueryParams,
    ) -> OrganizationPeopleListResponse:
        organization, _ = await self._require_active_org_access(actor_user_id, org_public_id)
        people = await self._repo.list_for_organization(organization.id, load_related=True)
        items = [self._to_list_item(person) for person in people]
        filtered = self._apply_people_filters(items, params)
        summary = self._build_directory_summary(filtered)
        page = filter_sort_paginate(
            filtered,
            params=params,
            search_fields=("name", "email", "phone", "added_by"),
            created_field="added_at",
            allowed_sort_fields=("added_at", "last_activity_at", "name", "relationship"),
            default_sort_by="last_activity_at",
            force_page_envelope=True,
        )
        if not isinstance(page, Page):
            raise RuntimeError("People directory must return a page envelope")
        return OrganizationPeopleListResponse(
            items=page.items,
            total=page.total,
            page=page.page,
            page_size=page.page_size,
            total_pages=page.total_pages,
            offset=page.offset,
            limit=page.limit,
            summary=summary,
        )

    async def get_detail(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        person_public_id: UUID,
    ) -> OrganizationPersonDetailResponse:
        organization, _ = await self._require_active_org_access(actor_user_id, org_public_id)
        person = await self._repo.get_by_public_id(organization.id, person_public_id, load_related=True)
        if person is None:
            raise NotFoundError("Organization person not found")

        relationship_summary = self._build_relationship_summary(person)
        passport_preview = await self._build_passport_preview(person)
        employment_verifications = self._build_employment_verifications(person)
        shared_evidence = await self._build_shared_evidence(person)
        activity = self._build_activity(person)
        internal_notes = [self._to_note_response(note, actor_user_id) for note in person.notes]
        verification_summary = self._build_verification_summary(person)

        return OrganizationPersonDetailResponse(
            id=person.public_id,
            public_id=person.public_id,
            summary=OrganizationPersonSummaryResponse(
                full_name=person.full_name,
                email=person.primary_email,
                phone=person.primary_phone,
                linked_user_id=person.linked_user_id,
            ),
            passport_preview=passport_preview,
            verification_summary=verification_summary,
            employment_verifications=employment_verifications,
            shared_evidence=shared_evidence,
            activity=activity,
            internal_notes=internal_notes,
            organization_relationship=relationship_summary,
        )

    async def add_note(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        person_public_id: UUID,
        payload: OrganizationPersonNoteRequest,
    ) -> OrganizationPersonNoteResponse:
        organization, _ = await self._require_active_org_access(actor_user_id, org_public_id)
        person = await self._repo.get_by_public_id(organization.id, person_public_id, load_related=False)
        if person is None:
            raise NotFoundError("Organization person not found")
        note = OrganizationPersonNote(
            organization_person_id=person.id,
            author_user_id=actor_user_id,
            body=payload.body,
        )
        await self._repo.add_note(note)
        await self._session.commit()
        refreshed = await self._repo.get_note_by_public_id(person.id, note.public_id)
        if refreshed is None:
            raise NotFoundError("Organization person note not found")
        return self._to_note_response(refreshed, actor_user_id)

    async def update_note(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        person_public_id: UUID,
        note_public_id: UUID,
        payload: OrganizationPersonNoteRequest,
    ) -> OrganizationPersonNoteResponse:
        organization, _ = await self._require_active_org_access(actor_user_id, org_public_id)
        person = await self._repo.get_by_public_id(organization.id, person_public_id, load_related=False)
        if person is None:
            raise NotFoundError("Organization person not found")
        note = await self._repo.get_note_by_public_id(person.id, note_public_id)
        if note is None:
            raise NotFoundError("Organization person note not found")
        if note.author_user_id != actor_user_id:
            raise ForbiddenError("Only the note author can update this note")
        note.body = payload.body
        await self._session.commit()
        refreshed = await self._repo.get_note_by_public_id(person.id, note.public_id)
        if refreshed is None:
            raise NotFoundError("Organization person note not found")
        return self._to_note_response(refreshed, actor_user_id)

    async def delete_note(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        person_public_id: UUID,
        note_public_id: UUID,
    ) -> None:
        organization, _ = await self._require_active_org_access(actor_user_id, org_public_id)
        person = await self._repo.get_by_public_id(organization.id, person_public_id, load_related=False)
        if person is None:
            raise NotFoundError("Organization person not found")
        note = await self._repo.get_note_by_public_id(person.id, note_public_id)
        if note is None:
            raise NotFoundError("Organization person note not found")
        if note.author_user_id != actor_user_id:
            raise ForbiddenError("Only the note author can delete this note")
        await self._repo.delete_note(note)
        await self._session.commit()

    async def resolve_for_trust_invitation(
        self,
        invitation: TrustInvitation,
        *,
        actor_user_id: UUID | None = None,
    ) -> OrganizationPerson:
        person = await self._resolve_person(
            organization_id=invitation.organization_id,
            existing_person_id=invitation.organization_person_id,
            linked_user_id=invitation.accepted_by_user_id,
            full_name=invitation.subject_name,
            email=invitation.subject_email,
            phone=invitation.subject_phone,
            relationship=(
                OrganizationPersonRelationship.CANDIDATE
                if invitation.accepted_by_user_id is not None
                else OrganizationPersonRelationship.FUTURE_EMPLOYEE
            ),
            added_by_user_id=invitation.created_by_user_id,
            added_at=invitation.created_at,
            last_activity_at=self._trust_invitation_last_activity(invitation),
            source_type="trust_invitation",
            source_public_id=invitation.public_id,
            actor_user_id=actor_user_id or invitation.created_by_user_id,
        )
        invitation.organization_person_id = person.id
        return person

    async def resolve_for_verification_request(
        self,
        request: VerificationRequest,
        *,
        actor_user_id: UUID | None = None,
        employment: Employment | None = None,
    ) -> OrganizationPerson | None:
        if request.organization_id is None:
            return None
        linked_user_id = request.subject_user_id
        phone = None
        if linked_user_id is not None:
            linked_user = await self._users.get_by_id(linked_user_id)
            phone = linked_user.phone if linked_user is not None else None
        resolved_employment = employment
        if resolved_employment is None and request.employment_id is not None:
            resolved_employment = await self._employments.get_active_by_id(request.employment_id)
        person = await self._resolve_person(
            organization_id=request.organization_id,
            existing_person_id=request.organization_person_id,
            linked_user_id=linked_user_id,
            full_name=request.subject_name,
            email=request.subject_email,
            phone=phone,
            relationship=self._infer_relationship_from_employment(resolved_employment),
            added_by_user_id=request.requested_by_user_id,
            added_at=request.created_at,
            last_activity_at=self._verification_request_last_activity(request),
            source_type="verification_request",
            source_public_id=request.public_id,
            actor_user_id=actor_user_id or request.requested_by_user_id,
        )
        request.organization_person_id = person.id
        if resolved_employment is not None and resolved_employment.organization_person_id in {None, person.id}:
            resolved_employment.organization_person_id = person.id
        return person

    async def upsert_passport_access(
        self,
        *,
        organization_person_id: UUID,
        passport_share_link_id: UUID,
        owner_user_id: UUID,
        access_state: OrganizationPersonPassportAccessState,
        permissions_snapshot: dict[str, Any],
        granted_at: datetime | None = None,
        expires_at: datetime | None = None,
        revoked_at: datetime | None = None,
        granted_via_source_type: str | None = None,
        granted_via_source_public_id: str | None = None,
    ) -> OrganizationPersonPassportAccess:
        existing = await self._repo.get_passport_access_by_share(organization_person_id, passport_share_link_id)
        if existing is not None:
            existing.access_state = access_state
            existing.permissions_snapshot = permissions_snapshot
            existing.granted_at = granted_at or existing.granted_at
            existing.expires_at = expires_at
            existing.revoked_at = revoked_at
            existing.granted_via_source_type = granted_via_source_type
            existing.granted_via_source_public_id = granted_via_source_public_id
            await self._session.flush()
            return existing
        access = OrganizationPersonPassportAccess(
            organization_person_id=organization_person_id,
            passport_share_link_id=passport_share_link_id,
            owner_user_id=owner_user_id,
            access_state=access_state,
            granted_at=granted_at or datetime.now(tz=UTC),
            expires_at=expires_at,
            revoked_at=revoked_at,
            permissions_snapshot=permissions_snapshot,
            granted_via_source_type=granted_via_source_type,
            granted_via_source_public_id=granted_via_source_public_id,
        )
        return await self._repo.add_passport_access(access)

    async def _require_active_org_access(self, actor_user_id: UUID, org_public_id: UUID):
        organization = await self._organizations.get_by_public_id(org_public_id)
        if organization is None:
            raise NotFoundError("Organization not found")
        membership = await self._organizations.get_membership(organization.id, actor_user_id)
        if membership is None:
            raise NotFoundError("Organization not found")
        if membership.suspended_at is not None:
            raise ForbiddenError("Organization membership is suspended")
        if organization.suspended_at is not None:
            raise ForbiddenError("Organization access is suspended")
        return organization, membership

    async def _resolve_person(
        self,
        *,
        organization_id: UUID,
        existing_person_id: UUID | None,
        linked_user_id: UUID | None,
        full_name: str,
        email: str | None,
        phone: str | None,
        relationship: OrganizationPersonRelationship,
        added_by_user_id: UUID | None,
        added_at: datetime | None,
        last_activity_at: datetime | None,
        source_type: str,
        source_public_id: UUID,
        actor_user_id: UUID | None,
    ) -> OrganizationPerson:
        normalized_email = self._normalize_email(email)
        normalized_phone = self._normalize_phone(phone)
        resolution_method = "created"
        confidence = Decimal("0.70")

        person = None
        if existing_person_id is not None:
            person = await self._repo.get_by_id(existing_person_id, load_related=False)
            resolution_method = "existing_link"
            confidence = Decimal("1.00")
        if person is None and linked_user_id is not None:
            person = await self._repo.find_by_linked_user(organization_id, linked_user_id)
            if person is not None:
                resolution_method = "linked_user"
                confidence = Decimal("1.00")
        if person is None and normalized_email is not None:
            person = await self._repo.find_by_primary_email(organization_id, normalized_email)
            if person is None:
                person = await self._repo.find_by_identifier(
                    organization_id,
                    OrganizationPersonIdentifierType.EMAIL.value,
                    normalized_email,
                )
            if person is not None:
                resolution_method = "email"
                confidence = Decimal("0.95")
        if person is None and normalized_phone is not None:
            person = await self._repo.find_by_primary_phone(organization_id, normalized_phone)
            if person is None:
                person = await self._repo.find_by_identifier(
                    organization_id,
                    OrganizationPersonIdentifierType.PHONE.value,
                    normalized_phone,
                )
            if person is not None:
                resolution_method = "phone"
                confidence = Decimal("0.90")

        if person is None:
            person = OrganizationPerson(
                organization_id=organization_id,
                linked_user_id=linked_user_id,
                full_name=full_name,
                primary_email=normalized_email,
                primary_phone=normalized_phone,
                relationship=relationship,
                added_by_user_id=added_by_user_id,
                added_at=added_at or datetime.now(tz=UTC),
                last_activity_at=last_activity_at or added_at,
                resolution_state="resolved",
                resolution_method=resolution_method,
                resolution_confidence=confidence,
                resolution_metadata=self._build_resolution_metadata(
                    source_type=source_type,
                    source_public_id=source_public_id,
                    actor_user_id=actor_user_id,
                ),
            )
            await self._repo.create(person)
        else:
            if linked_user_id is not None and person.linked_user_id is None:
                person.linked_user_id = linked_user_id
            person.full_name = full_name or person.full_name
            if normalized_email is not None and person.primary_email is None:
                person.primary_email = normalized_email
            if normalized_phone is not None and person.primary_phone is None:
                person.primary_phone = normalized_phone
            person.relationship = self._merge_relationship(person.relationship, relationship)
            if added_by_user_id is not None and person.added_by_user_id is None:
                person.added_by_user_id = added_by_user_id
            if added_at is not None and (person.added_at is None or added_at < person.added_at):
                person.added_at = added_at
            person.last_activity_at = self._max_dt(person.last_activity_at, last_activity_at)
            person.resolution_state = "resolved"
            person.resolution_method = resolution_method
            person.resolution_confidence = confidence
            person.resolution_metadata = self._build_resolution_metadata(
                source_type=source_type,
                source_public_id=source_public_id,
                actor_user_id=actor_user_id,
            )

        if normalized_email is not None:
            await self._ensure_identifier(
                person=person,
                identifier_type=OrganizationPersonIdentifierType.EMAIL,
                normalized_value=normalized_email,
                raw_value=email,
                is_primary=person.primary_email == normalized_email,
            )
        if normalized_phone is not None:
            await self._ensure_identifier(
                person=person,
                identifier_type=OrganizationPersonIdentifierType.PHONE,
                normalized_value=normalized_phone,
                raw_value=phone,
                is_primary=person.primary_phone == normalized_phone,
            )
        await self._session.flush()
        return person

    async def _ensure_identifier(
        self,
        *,
        person: OrganizationPerson,
        identifier_type: OrganizationPersonIdentifierType,
        normalized_value: str,
        raw_value: str | None,
        is_primary: bool,
    ) -> OrganizationPersonIdentifier:
        existing = await self._repo.get_identifier(person.id, identifier_type.value, normalized_value)
        if existing is not None:
            existing.raw_value = raw_value
            existing.is_primary = existing.is_primary or is_primary
            await self._session.flush()
            return existing
        identifier = OrganizationPersonIdentifier(
            organization_person_id=person.id,
            organization_id=person.organization_id,
            identifier_type=identifier_type,
            normalized_value=normalized_value,
            raw_value=raw_value,
            is_primary=is_primary,
        )
        return await self._repo.create_identifier(identifier)

    def _apply_people_filters(
        self,
        items: list[OrganizationPersonListItemResponse],
        params: OrganizationPeopleListQueryParams,
    ) -> list[OrganizationPersonListItemResponse]:
        filtered = list(items)
        if params.relationship is not None:
            filtered = [item for item in filtered if item.relationship == params.relationship]
        if params.invitation_status is not None:
            filtered = [item for item in filtered if item.invitation_status == params.invitation_status]
        if params.verification_status is not None:
            filtered = [item for item in filtered if item.verification_status == params.verification_status]
        if params.passport_status is not None:
            filtered = [item for item in filtered if item.passport_status == params.passport_status]
        if params.trust_state is not None:
            filtered = [item for item in filtered if item.trust_state == params.trust_state]
        if params.added_by:
            needle = params.added_by.strip().lower()
            filtered = [
                item for item in filtered
                if item.added_by is not None and needle in item.added_by.lower()
            ]
        return filtered

    def _build_directory_summary(
        self,
        items: list[OrganizationPersonListItemResponse],
    ) -> OrganizationPeopleDirectorySummary:
        by_relationship: dict[str, int] = {}
        by_invitation_status: dict[str, int] = {}
        by_verification_status: dict[str, int] = {}
        by_passport_status: dict[str, int] = {}
        by_trust_state: dict[str, int] = {}
        for item in items:
            by_relationship[item.relationship.value] = by_relationship.get(item.relationship.value, 0) + 1
            by_invitation_status[item.invitation_status.value] = by_invitation_status.get(item.invitation_status.value, 0) + 1
            by_verification_status[item.verification_status.value] = by_verification_status.get(item.verification_status.value, 0) + 1
            by_passport_status[item.passport_status.value] = by_passport_status.get(item.passport_status.value, 0) + 1
            by_trust_state[item.trust_state.value] = by_trust_state.get(item.trust_state.value, 0) + 1
        return OrganizationPeopleDirectorySummary(
            total_people=len(items),
            by_relationship=by_relationship,
            by_invitation_status=by_invitation_status,
            by_verification_status=by_verification_status,
            by_passport_status=by_passport_status,
            by_trust_state=by_trust_state,
        )

    def _to_list_item(self, person: OrganizationPerson) -> OrganizationPersonListItemResponse:
        relationship = self._derive_person_relationship(person)
        invitation_status = self._derive_invitation_status(person)
        verification_status = self._derive_verification_status(person)
        passport_status = self._derive_passport_status(person)
        trust_state = self._derive_trust_state(
            invitation_status=invitation_status,
            verification_status=verification_status,
            passport_status=passport_status,
        )
        return OrganizationPersonListItemResponse(
            id=person.public_id,
            public_id=person.public_id,
            name=person.full_name,
            full_name=person.full_name,
            email=person.primary_email,
            phone=person.primary_phone,
            relationship=relationship,
            trust_state=trust_state,
            invitation_status=invitation_status,
            verification_status=verification_status,
            passport_status=passport_status,
            added_by=person.added_by_user.full_name if person.added_by_user is not None else None,
            added_at=person.added_at,
            last_activity_at=self._person_last_activity_at(person),
            summary_counts=OrganizationPersonSummaryCounts(
                invitations=len(person.trust_invitations),
                verification_requests=len(person.verification_requests),
                shared_evidence_items=sum(
                    1
                    for request in person.verification_requests
                    for evidence in request.evidence_items
                    if evidence.document_id is not None or evidence.employment_document_id is not None
                ),
                internal_notes=len(person.notes),
            ),
        )

    def _build_relationship_summary(
        self,
        person: OrganizationPerson,
    ) -> OrganizationPersonRelationshipSummaryResponse:
        relationship = self._derive_person_relationship(person)
        invitation_status = self._derive_invitation_status(person)
        verification_status = self._derive_verification_status(person)
        passport_status = self._derive_passport_status(person)
        trust_state = self._derive_trust_state(
            invitation_status=invitation_status,
            verification_status=verification_status,
            passport_status=passport_status,
        )
        return OrganizationPersonRelationshipSummaryResponse(
            relationship=relationship,
            trust_state=trust_state,
            invitation_status=invitation_status,
            verification_status=verification_status,
            passport_status=passport_status,
            added_by=person.added_by_user.full_name if person.added_by_user is not None else None,
            added_at=person.added_at,
            last_activity_at=self._person_last_activity_at(person),
            resolution_state=person.resolution_state,
            resolution_method=person.resolution_method,
            resolution_confidence=float(person.resolution_confidence) if person.resolution_confidence is not None else None,
            resolution_metadata=dict(person.resolution_metadata or {}),
        )

    async def _build_passport_preview(
        self,
        person: OrganizationPerson,
    ) -> OrganizationPersonPassportPreviewResponse:
        access = self._latest_passport_access(person)
        status = self._derive_passport_status(person)
        if access is None or status in {
            OrganizationPersonPassportStatusSummary.NOT_SHARED,
            OrganizationPersonPassportStatusSummary.EXPIRED,
            OrganizationPersonPassportStatusSummary.ACCESS_REVOKED,
        }:
            return OrganizationPersonPassportPreviewResponse(status=status)

        permissions = PassportSharePermissions.model_validate(access.permissions_snapshot or {})
        vault = await self._public_passport.build_vault_for_user(access.owner_user_id, permissions)
        claims: list[OrganizationPersonPassportClaimResponse] = []
        if person.full_name:
            claims.append(
                OrganizationPersonPassportClaimResponse(
                    label="Full name",
                    value=person.full_name,
                    status="verified" if person.linked_user_id is not None else "candidate_provided",
                )
            )
        if person.primary_email:
            claims.append(
                OrganizationPersonPassportClaimResponse(
                    label="Work email",
                    value=person.primary_email,
                    status="verified" if person.linked_user_id is not None else "candidate_provided",
                )
            )
        if vault.employments:
            latest_employment = vault.employments[0]
            claims.append(
                OrganizationPersonPassportClaimResponse(
                    label="Most recent employer",
                    value=latest_employment.employer_legal_name,
                    status=self._passport_claim_status_from_verification(latest_employment.verification_status),
                    source="employment",
                )
            )
            claims.append(
                OrganizationPersonPassportClaimResponse(
                    label="Employment tenure",
                    value=self._format_employment_tenure(latest_employment.start_date, latest_employment.end_date),
                    status=self._passport_claim_status_from_verification(latest_employment.verification_status),
                    source="employment",
                )
            )
        if vault.educations:
            highest_education = vault.educations[0]
            claims.append(
                OrganizationPersonPassportClaimResponse(
                    label="Highest education",
                    value=highest_education.degree or highest_education.institution_name,
                    status="candidate_provided",
                    source="education",
                )
            )
        return OrganizationPersonPassportPreviewResponse(
            status=status,
            shared_at=access.granted_at,
            expires_at=access.expires_at,
            revoked_at=access.revoked_at,
            permissions=permissions.model_dump(),
            claims=claims,
        )

    def _build_verification_summary(
        self,
        person: OrganizationPerson,
    ) -> OrganizationPersonVerificationSummaryResponse:
        statuses = [self._map_verification_status(request.status) for request in person.verification_requests]
        latest_status = (
            self._derive_verification_status(person)
            if person.verification_requests
            else OrganizationPersonVerificationStatusSummary.NOT_STARTED
        )
        return OrganizationPersonVerificationSummaryResponse(
            latest_status=latest_status,
            total_requests=len(person.verification_requests),
            completed_requests=sum(1 for status in statuses if status == OrganizationPersonVerificationStatusSummary.COMPLETED),
            active_requests=sum(1 for status in statuses if status in _ACTIVE_VERIFICATION_SUMMARIES),
            clarification_required_requests=sum(
                1 for status in statuses if status == OrganizationPersonVerificationStatusSummary.CLARIFICATION_REQUIRED
            ),
        )

    def _build_employment_verifications(
        self,
        person: OrganizationPerson,
    ) -> list[OrganizationPersonEmploymentVerificationResponse]:
        requests = sorted(
            person.verification_requests,
            key=lambda item: item.created_at,
            reverse=True,
        )
        return [
            OrganizationPersonEmploymentVerificationResponse(
                id=request.public_id,
                public_id=request.public_id,
                status=self._map_verification_status(request.status).value,
                requested_by=self._event_actor_name_from_user_id(request.requested_by_user_id),
                requested_at=request.created_at,
                request_type=request.request_type.value if isinstance(request.request_type, VerificationRequestType) else str(request.request_type),
                request_public_id=request.public_id,
            )
            for request in requests
        ]

    async def _build_shared_evidence(
        self,
        person: OrganizationPerson,
    ) -> list[OrganizationPersonSharedEvidenceResponse]:
        items: list[OrganizationPersonSharedEvidenceResponse] = []
        for request in sorted(person.verification_requests, key=lambda item: item.created_at, reverse=True):
            for evidence in request.evidence_items:
                if evidence.document_id is None and evidence.employment_document_id is None:
                    continue
                document = None
                if evidence.employment_document_id is not None:
                    document = await self._employment_documents.get_active_by_id(evidence.employment_document_id)
                elif evidence.document_id is not None:
                    document = await self._user_documents.get_active_by_id(evidence.document_id)

                download_url = None
                download_url_expires_in_seconds = None
                if document is not None and getattr(document, "object_key", None) and self._settings.s3_documents_bucket:
                    download_url_expires_in_seconds = 300
                    download_url = await generate_presigned_get_url(
                        bucket=self._settings.s3_documents_bucket,
                        object_key=document.object_key,
                        ttl_seconds=download_url_expires_in_seconds,
                        settings=self._settings,
                    )
                status = "available"
                if request.status == VerificationRequestStatus.CANCELLED:
                    status = "revoked"
                elif request.status == VerificationRequestStatus.EXPIRED:
                    status = "expired"
                items.append(
                    OrganizationPersonSharedEvidenceResponse(
                        id=evidence.public_id,
                        public_id=evidence.public_id,
                        request_public_id=request.public_id,
                        type=evidence.evidence_type,
                        shared_at=evidence.created_at,
                        status=status,
                        original_filename=getattr(document, "original_filename", None),
                        mime_type=getattr(document, "content_type", None),
                        file_size=getattr(document, "byte_size", None),
                        download_url=download_url,
                        download_url_expires_in_seconds=download_url_expires_in_seconds,
                    )
                )
        return items

    def _build_activity(
        self,
        person: OrganizationPerson,
    ) -> list[OrganizationPersonActivityResponse]:
        items: list[OrganizationPersonActivityResponse] = [
            OrganizationPersonActivityResponse(
                id=f"person:{person.public_id}:added",
                kind="added",
                label="Person added to workspace",
                actor=person.added_by_user.full_name if person.added_by_user is not None and person.added_by_user.full_name else "System",
                at=person.added_at,
                source_type="organization_person",
                source_public_id=str(person.public_id),
            )
        ]

        for invitation in person.trust_invitations:
            for event in invitation.events:
                items.append(
                    OrganizationPersonActivityResponse(
                        id=f"invitation:{invitation.public_id}:{event.id}",
                        kind=self._invitation_activity_kind(event.event_type),
                        label=self._invitation_activity_label(event.event_type),
                        actor=(
                            event.actor_user.full_name
                            if event.actor_user is not None and event.actor_user.full_name
                            else self._fallback_activity_actor("organization")
                        ),
                        at=event.occurred_at,
                        source_type="trust_invitation",
                        source_public_id=str(invitation.public_id),
                    )
                )

        for request in person.verification_requests:
            for event in request.events:
                items.append(
                    OrganizationPersonActivityResponse(
                        id=f"verification:{request.public_id}:{event.id}",
                        kind=self._verification_activity_kind(event.event_type, event.new_status),
                        label=self._verification_activity_label(event.event_type, event.new_status),
                        actor=self._fallback_activity_actor(event.event_source.value),
                        at=event.created_at,
                        request_public_id=request.public_id,
                        source_type="verification_request",
                        source_public_id=str(request.public_id),
                    )
                )

        for access in person.passport_access_entries:
            items.append(
                OrganizationPersonActivityResponse(
                    id=f"passport:{access.public_id}:granted",
                    kind="shared",
                    label="Trust Passport shared with your organization",
                    actor="Candidate",
                    at=access.granted_at,
                    source_type="passport_access",
                    source_public_id=str(access.public_id),
                )
            )
            if access.revoked_at is not None:
                items.append(
                    OrganizationPersonActivityResponse(
                        id=f"passport:{access.public_id}:revoked",
                        kind="revoked",
                        label="Candidate revoked passport access",
                        actor="Candidate",
                        at=access.revoked_at,
                        source_type="passport_access",
                        source_public_id=str(access.public_id),
                    )
                )
            elif access.expires_at is not None and access.expires_at <= datetime.now(tz=UTC):
                items.append(
                    OrganizationPersonActivityResponse(
                        id=f"passport:{access.public_id}:expired",
                        kind="expired",
                        label="Trust Passport access expired",
                        actor="System",
                        at=access.expires_at,
                        source_type="passport_access",
                        source_public_id=str(access.public_id),
                    )
                )

        for note in person.notes:
            items.append(
                OrganizationPersonActivityResponse(
                    id=f"note:{note.public_id}",
                    kind="note",
                    label="Internal note added",
                    actor=note.author_user.full_name if note.author_user is not None and note.author_user.full_name else "Team member",
                    at=note.created_at,
                    source_type="organization_person_note",
                    source_public_id=str(note.public_id),
                )
            )

        for employment in person.employments:
            items.append(
                OrganizationPersonActivityResponse(
                    id=f"employment:{employment.id}",
                    kind="employment",
                    label="Employment record linked",
                    actor="System",
                    at=employment.created_at,
                    source_type="employment",
                    source_public_id=str(employment.id),
                )
            )

        items.sort(key=lambda item: item.at, reverse=True)
        return items

    def _to_note_response(self, note: OrganizationPersonNote, actor_user_id: UUID) -> OrganizationPersonNoteResponse:
        return OrganizationPersonNoteResponse(
            id=note.public_id,
            public_id=note.public_id,
            author=note.author_user.full_name if note.author_user is not None else None,
            author_user_id=note.author_user_id,
            body=note.body,
            at=note.created_at,
            created_at=note.created_at,
            updated_at=note.updated_at,
            owned_by_current_user=note.author_user_id == actor_user_id,
        )

    def _derive_person_relationship(self, person: OrganizationPerson) -> OrganizationPersonRelationship:
        relationship = person.relationship
        for employment in person.employments:
            relationship = self._merge_relationship(
                relationship,
                self._infer_relationship_from_employment(employment),
            )
        return relationship

    def _derive_invitation_status(self, person: OrganizationPerson) -> OrganizationPersonInvitationStatusSummary:
        if not person.trust_invitations:
            return OrganizationPersonInvitationStatusSummary.NOT_INVITED
        latest = max(person.trust_invitations, key=self._trust_invitation_last_activity)
        mapped = _INVITATION_STATUS_MAP.get(latest.status, OrganizationPersonInvitationStatusSummary.NOT_INVITED)
        if latest.opened_at is not None and latest.status == TrustInvitationStatus.PENDING:
            return OrganizationPersonInvitationStatusSummary.OPENED
        return mapped

    def _derive_verification_status(self, person: OrganizationPerson) -> OrganizationPersonVerificationStatusSummary:
        if not person.verification_requests:
            return OrganizationPersonVerificationStatusSummary.NOT_STARTED
        latest = max(person.verification_requests, key=self._verification_request_last_activity)
        return self._map_verification_status(latest.status)

    def _derive_passport_status(self, person: OrganizationPerson) -> OrganizationPersonPassportStatusSummary:
        access = self._latest_passport_access(person)
        if access is None:
            return OrganizationPersonPassportStatusSummary.NOT_SHARED
        if access.revoked_at is not None or access.access_state == OrganizationPersonPassportAccessState.REVOKED:
            return OrganizationPersonPassportStatusSummary.ACCESS_REVOKED
        if access.expires_at is not None and access.expires_at <= datetime.now(tz=UTC):
            return OrganizationPersonPassportStatusSummary.EXPIRED
        if access.expires_at is not None and access.expires_at <= datetime.now(tz=UTC) + timedelta(days=7):
            return OrganizationPersonPassportStatusSummary.EXPIRING_SOON
        return OrganizationPersonPassportStatusSummary.ACTIVE

    def _derive_trust_state(
        self,
        *,
        invitation_status: OrganizationPersonInvitationStatusSummary,
        verification_status: OrganizationPersonVerificationStatusSummary,
        passport_status: OrganizationPersonPassportStatusSummary,
    ) -> OrganizationPersonTrustState:
        if passport_status == OrganizationPersonPassportStatusSummary.ACCESS_REVOKED:
            return OrganizationPersonTrustState.REVOKED
        if verification_status == OrganizationPersonVerificationStatusSummary.COMPLETED:
            return OrganizationPersonTrustState.VERIFIED
        if passport_status in {
            OrganizationPersonPassportStatusSummary.ACTIVE,
            OrganizationPersonPassportStatusSummary.EXPIRING_SOON,
            OrganizationPersonPassportStatusSummary.EXPIRED,
        } or invitation_status == OrganizationPersonInvitationStatusSummary.ACCEPTED:
            return OrganizationPersonTrustState.PARTIALLY_VERIFIED
        if invitation_status in {
            OrganizationPersonInvitationStatusSummary.DRAFT,
            OrganizationPersonInvitationStatusSummary.SENT,
            OrganizationPersonInvitationStatusSummary.OPENED,
        } or verification_status in _ACTIVE_VERIFICATION_SUMMARIES:
            return OrganizationPersonTrustState.PENDING
        return OrganizationPersonTrustState.UNKNOWN

    def _person_last_activity_at(self, person: OrganizationPerson) -> datetime | None:
        timestamps = [person.last_activity_at, person.added_at]
        timestamps.extend(self._trust_invitation_last_activity(invitation) for invitation in person.trust_invitations)
        timestamps.extend(self._verification_request_last_activity(request) for request in person.verification_requests)
        timestamps.extend(note.updated_at for note in person.notes)
        for access in person.passport_access_entries:
            timestamps.append(access.granted_at)
            timestamps.append(access.revoked_at)
            timestamps.append(access.expires_at)
        timestamps.extend(employment.updated_at for employment in person.employments)
        values = [value for value in timestamps if value is not None]
        return max(values) if values else None

    def _trust_invitation_last_activity(self, invitation: TrustInvitation) -> datetime:
        candidates = [
            invitation.cancelled_at,
            invitation.accepted_at,
            invitation.opened_at,
            invitation.sent_at,
            invitation.updated_at,
            invitation.created_at,
        ]
        event_times = [event.occurred_at for event in invitation.events]
        candidates.extend(event_times)
        return max(value for value in candidates if value is not None)

    def _verification_request_last_activity(self, request: VerificationRequest) -> datetime:
        candidates = [
            request.updated_at,
            request.created_at,
            request.candidate_response_submitted_at,
            request.accepted_at,
        ]
        candidates.extend(event.created_at for event in request.events)
        return max(value for value in candidates if value is not None)

    def _latest_passport_access(self, person: OrganizationPerson) -> OrganizationPersonPassportAccess | None:
        if not person.passport_access_entries:
            return None
        return max(person.passport_access_entries, key=lambda item: item.granted_at)

    def _map_verification_status(
        self,
        status: VerificationRequestStatus | str,
    ) -> OrganizationPersonVerificationStatusSummary:
        resolved = status if isinstance(status, VerificationRequestStatus) else VerificationRequestStatus(status)
        return _VERIFICATION_STATUS_MAP[resolved]

    def _merge_relationship(
        self,
        current: OrganizationPersonRelationship,
        incoming: OrganizationPersonRelationship,
    ) -> OrganizationPersonRelationship:
        if incoming == current:
            return current
        priority = {
            OrganizationPersonRelationship.CANDIDATE: 1,
            OrganizationPersonRelationship.FUTURE_EMPLOYEE: 2,
            OrganizationPersonRelationship.CONTRACTOR: 3,
            OrganizationPersonRelationship.EMPLOYEE: 4,
            OrganizationPersonRelationship.FORMER_EMPLOYEE: 5,
        }
        return incoming if priority[incoming] >= priority[current] else current

    def _infer_relationship_from_employment(
        self,
        employment: Employment | None,
    ) -> OrganizationPersonRelationship:
        if employment is None:
            return OrganizationPersonRelationship.CANDIDATE
        employment_type = str(employment.employment_type)
        if employment.end_date is not None and employment.end_date < datetime.now(tz=UTC).date():
            return OrganizationPersonRelationship.FORMER_EMPLOYEE
        if employment_type in {"contract", "freelance", "gig"}:
            return OrganizationPersonRelationship.CONTRACTOR
        return OrganizationPersonRelationship.EMPLOYEE

    def _build_resolution_metadata(
        self,
        *,
        source_type: str,
        source_public_id: UUID,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source_type": source_type,
            "source_public_id": str(source_public_id),
        }
        if actor_user_id is not None:
            payload["actor_user_id"] = str(actor_user_id)
        return payload

    def _normalize_email(self, email: str | None) -> str | None:
        if email is None:
            return None
        normalized = email.strip().lower()
        return normalized or None

    def _normalize_phone(self, phone: str | None) -> str | None:
        if phone is None:
            return None
        normalized = _PHONE_CLEAN_RE.sub("", phone.strip())
        return normalized or None

    def _max_dt(self, left: datetime | None, right: datetime | None) -> datetime | None:
        if left is None:
            return right
        if right is None:
            return left
        return max(left, right)

    def _event_actor_name_from_user_id(self, user_id: UUID | None) -> str | None:
        return None if user_id is None else "Organization member"

    def _fallback_activity_actor(self, source: str) -> str:
        return {
            "candidate": "Candidate",
            "organization": "Organization",
            "admin": "Kairo Trust Engine",
        }.get(source, self._humanize_token(source))

    def _invitation_activity_kind(self, event_type: str) -> str:
        return {
            "created": "added",
            "sent": "invited",
            "resent": "invited",
            "opened": "opened",
            "accepted": "accepted",
            "cancelled": "revoked",
            "expired": "expired",
            "delivery_failed": "unable",
        }.get(event_type, "invited")

    def _invitation_activity_label(self, event_type: str) -> str:
        return {
            "created": "Person added to workspace",
            "sent": "Trust invitation sent",
            "resent": "Trust invitation resent",
            "opened": "Invitation opened",
            "accepted": "Invitation accepted",
            "cancelled": "Invitation cancelled",
            "expired": "Invitation expired",
            "delivery_failed": "Invitation delivery failed",
        }.get(event_type, self._humanize_token(event_type))

    def _verification_activity_kind(
        self,
        event_type: str,
        new_status: VerificationRequestStatus | None,
    ) -> str:
        if event_type == "verification_request_created":
            return "request"
        if "clarification" in event_type or new_status == VerificationRequestStatus.AWAITING_INFORMATION:
            return "clarification-req"
        if new_status == VerificationRequestStatus.VERIFIED:
            return "completed"
        if new_status in {
            VerificationRequestStatus.REJECTED,
            VerificationRequestStatus.UNABLE_TO_VERIFY,
        }:
            return "unable"
        if new_status == VerificationRequestStatus.CANCELLED:
            return "revoked"
        if event_type in {"verification_request_information_submitted", "verification_submitted"}:
            return "submitted"
        return "request"

    def _verification_activity_label(
        self,
        event_type: str,
        new_status: VerificationRequestStatus | None,
    ) -> str:
        labels = {
            "verification_request_created": "Verification request created",
            "verification_request_subject_accepted": "Consent granted for verification",
            "verification_request_information_requested": "Clarification requested from candidate",
            "verification_request_information_submitted": "Clarification received",
            "verification_submitted": "Candidate information submitted",
            "verification_request_verified": "Verification completed",
            "verification_completed": "Verification completed",
            "verification_request_rejected": "Unable to complete verification",
            "verification_request_cancelled": "Verification request cancelled",
            "verification_request_internal_note_updated": "Internal note updated",
            "verification_request_reviewer_assigned": "Reviewer assigned",
        }
        if event_type in labels:
            return labels[event_type]
        if new_status is not None:
            return f"Verification status changed to {self._humanize_token(new_status.value)}"
        return self._humanize_token(event_type)

    def _passport_claim_status_from_verification(self, status: str | None) -> str:
        if status in {"approved", "verified"}:
            return "verified"
        if status in {"rejected", "cancelled", "expired"}:
            return "unable_to_verify"
        return "verification_pending"

    def _format_employment_tenure(self, start_date, end_date) -> str | None:  # noqa: ANN001
        if start_date is None:
            return None
        start_value = start_date.isoformat()
        end_value = end_date.isoformat() if end_date is not None else "present"
        return f"{start_value} to {end_value}"

    def _humanize_token(self, value: str) -> str:
        return value.replace("_", " ").strip().capitalize()
