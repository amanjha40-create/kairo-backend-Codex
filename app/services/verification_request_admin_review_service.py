"""Admin review workflow for verification requests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.admin_review.enums import (
    VerificationRequestEvidenceStatus,
    VerificationRequestReviewStatus,
    VerificationReviewCorrectionStatus,
    VerificationReviewNoteVisibility,
)
from app.core.permissions import Permission, has_permission
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.infrastructure.s3.presign import generate_presigned_get_url
from app.models.verification_request_review import VerificationRequestReview
from app.models.verification_review_correction import VerificationReviewCorrection
from app.models.verification_review_note import VerificationReviewNote
from app.repositories.organization import OrganizationRepository
from app.repositories.employment import EmploymentRepository
from app.repositories.employment_document import EmploymentDocumentRepository
from app.repositories.employer_verification import EmployerVerificationRepository
from app.repositories.trust_registry import TrustRegistryRepository
from app.repositories.user import UserRepository
from app.repositories.verification_request import VerificationRequestRepository
from app.repositories.verification_request_evidence import VerificationRequestEvidenceRepository
from app.repositories.verification_request_review import VerificationRequestReviewRepository
from app.repositories.verification_contact import VerificationContactRepository
from app.services.employer_verification_service import EmployerVerificationService
from app.config import Settings, get_settings
from app.schemas.employer_verification import EmployerVerificationRequestBody
from app.verification_requests.enums import VerificationContactReviewStatus, VerificationContactType
from app.schemas.pagination import ListQueryParams, Page, filter_sort_paginate
from app.schemas.admin_review_workflow import (
    AdminReviewAssignRequest,
    AdminReviewCorrectionRequest,
    AdminReviewCycleResponse,
    AdminReviewDecisionRequest,
    AdminReviewDetailResponse,
    AdminEvidenceDownloadResponse,
    AdminReviewEvidenceResponse,
    AdminReviewInternalNoteResponse,
    AdminReviewQueueItemResponse,
    AdminReviewerSummary,
    AdminOrganizationResolutionResponse,
    AdminRegistryResolutionResponse,
    AdminVerificationContactResponse,
    AdminReviewNoteCreateRequest,
    AdminReviewNoteResponse,
    AdminReviewOrganizationResolutionRequest,
    AdminReviewQueueResponse,
    AdminReviewTimelineResponse,
    AdminReviewWorkflowEnvelope,
    AdminVerificationContactReviewRequest,
)
from app.schemas.verification_request import (
    VerificationRequestCorrectionResponse,
    VerificationRequestEvidenceResponse,
    VerificationRequestResponse,
    VerificationRequestTimelineEventResponse,
    VerificationRequestTimelineResponse,
    VerificationContactResponse,
)
from app.services.verification_request_workflow_service import VerificationRequestWorkflowService
from app.verification_requests.enums import VerificationRequestEventSource, VerificationRequestStatus


def normalize_contact_review_status(
    review_status: VerificationContactReviewStatus | str,
) -> str:
    return review_status.value if isinstance(review_status, VerificationContactReviewStatus) else review_status


def normalize_contact_type(contact_type: VerificationContactType | str) -> str:
    return contact_type.value if isinstance(contact_type, VerificationContactType) else contact_type


class VerificationRequestAdminReviewService:
    """Platform-admin review stage for canonical verification requests."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._requests = VerificationRequestRepository(session)
        self._organizations = OrganizationRepository(session)
        self._employments = EmploymentRepository(session)
        self._employment_documents = EmploymentDocumentRepository(session)
        self._employer_verifications = EmployerVerificationRepository(session)
        self._registry = TrustRegistryRepository(session)
        self._users = UserRepository(session)
        self._evidence = VerificationRequestEvidenceRepository(session)
        self._reviews = VerificationRequestReviewRepository(session)
        self._contacts = VerificationContactRepository(session)
        self._settings = settings or get_settings()
        self._employer_outreach = EmployerVerificationService(session, self._settings)
        self._workflow = VerificationRequestWorkflowService(self._requests)

    async def get_queue(self, params: ListQueryParams | None = None) -> AdminReviewQueueResponse:
        items = await self._requests.list_by_status(
            [
                VerificationRequestStatus.PENDING_ADMIN_REVIEW.value,
                VerificationRequestStatus.PENDING_ADMIN_RE_REVIEW.value,
            ]
        )
        responses = [self._to_request_response(item) for item in items]
        page = filter_sort_paginate(
            responses,
            params=params or ListQueryParams(),
            search_fields=(
                "subject_name",
                "subject_email",
                "request_type",
                "status",
                "target_organization_name",
                "target_organization_email",
            ),
            allowed_sort_fields=("created_at", "updated_at", "subject_name", "subject_email", "status"),
            default_sort_by="created_at",
            force_page_envelope=True,
        )
        if not isinstance(page, Page):
            raise RuntimeError("Admin review queue must return a page envelope")
        return AdminReviewQueueResponse(
            items=[await self._to_queue_item(item) for item in page.items],
            total=page.total,
            page=page.page,
            page_size=page.page_size,
            total_pages=page.total_pages,
            offset=page.offset,
            limit=page.limit,
        )

    async def _to_queue_item(self, item: VerificationRequestResponse) -> AdminReviewQueueItemResponse:
        request = await self._get_required_request(item.public_id)
        review = await self._reviews.get_latest_review_for_request(request.id)
        reviewer = None
        if review is not None and review.assigned_reviewer_user_id is not None:
            user = await self._users.get_by_id(review.assigned_reviewer_user_id)
            if user is not None:
                reviewer = AdminReviewerSummary(
                    user_id=user.id,
                    full_name=user.full_name,
                    email=user.email,
                    role=user.role,
                )
        contact = await self._contacts.get_current(request.id)
        return AdminReviewQueueItemResponse(
            **item.model_dump(),
            assigned_reviewer=reviewer,
            contact_review_status=(normalize_contact_review_status(contact.review_status) if contact is not None else None),
            organization_resolution_status="resolved" if request.organization_id else "unresolved",
            registry_resolution_status=request.registry_resolution_state,
        )

    async def get_evidence_download_url(
        self,
        verification_request_public_id: UUID,
        evidence_public_id: UUID,
    ) -> AdminEvidenceDownloadResponse:
        request = await self._get_required_request(verification_request_public_id)
        evidence = await self._evidence.get_by_public_id(evidence_public_id)
        if evidence is None or evidence.verification_request_id != request.id:
            raise NotFoundError("Verification request evidence not found")
        if evidence.employment_document_id is None:
            raise ConflictError("Evidence is not backed by an employment document")
        document = await self._employment_documents.get_active_by_id(evidence.employment_document_id)
        if document is None or request.employment_id != document.employment_id:
            raise NotFoundError("Employment document not found")
        bucket = self._settings.s3_documents_bucket
        if not bucket:
            raise ConflictError("Document storage is not configured")
        ttl_seconds = 300
        download_url = await generate_presigned_get_url(
            bucket=bucket,
            object_key=document.object_key,
            ttl_seconds=ttl_seconds,
            settings=self._settings,
        )
        return AdminEvidenceDownloadResponse(
            evidence_public_id=evidence.public_id,
            download_url=download_url,
            expires_in_seconds=ttl_seconds,
        )

    async def get_detail(self, verification_request_public_id: UUID) -> AdminReviewDetailResponse:
        request = await self._get_required_request(verification_request_public_id)
        evidence_items = await self._evidence.list_for_request(request.id)
        reviews = await self._reviews.list_reviews_for_request(request.id)
        open_corrections = await self._reviews.list_open_corrections_for_request([review.id for review in reviews])
        review_public_ids = {review.id: review.public_id for review in reviews}
        notes = [
            note
            for note in await self._reviews.list_notes_for_request(list(review_public_ids))
            if note.visibility == VerificationReviewNoteVisibility.INTERNAL
        ]
        employment = (
            await self._employments.get_active_by_id(request.employment_id)
            if request.employment_id is not None
            else None
        )
        contacts = await self._contacts.list_versions(request.id)
        current_contact = next((item for item in contacts if item.superseded_at is None), None)
        organization = await self._organizations.get_by_id(request.organization_id) if request.organization_id else None
        registry_record = (
            await self._registry.get_by_id(request.registry_record_id)
            if request.registry_record_id is not None
            else None
        )
        employer_verification = await self._employer_verifications.get_by_verification_request_id(request.id)
        return AdminReviewDetailResponse(
            request=self._to_request_response(request),
            employer_verification_public_id=(
                employer_verification.public_id if employer_verification is not None else None
            ),
            employment=employment,
            verification_contact=self._to_admin_contact_response(current_contact) if current_contact else None,
            verification_contact_history=[self._to_admin_contact_response(item) for item in contacts],
            evidence=[await self._to_admin_evidence_response(item) for item in evidence_items],
            reviews=[self._to_review_response(review) for review in reviews],
            open_corrections=[self._to_correction_response(item) for item in open_corrections],
            internal_notes=[self._to_internal_note_response(item, review_public_ids) for item in notes],
            organization_resolution=AdminOrganizationResolutionResponse(
                status="resolved" if organization is not None else "unresolved",
                organization_public_id=organization.public_id if organization is not None else None,
                organization_name=organization.name if organization is not None else request.target_organization_name,
            ),
            registry_resolution=AdminRegistryResolutionResponse(
                status=request.registry_resolution_state,
                registry_record_public_id=registry_record.public_id if registry_record is not None else None,
                registry_code=registry_record.registry_code if registry_record is not None else None,
                registry_name=registry_record.display_name or registry_record.legal_name if registry_record is not None else None,
                resolution_method=request.registry_resolution_method,
                resolution_confidence=request.registry_resolution_confidence,
                resolution_metadata=dict(request.registry_resolution_metadata or {}),
            ),
        )

    async def _to_admin_evidence_response(self, evidence) -> AdminReviewEvidenceResponse:  # noqa: ANN001
        base = self._to_evidence_response(evidence)
        document = None
        if evidence.employment_document_id is not None:
            document = await self._employment_documents.get_active_by_id(evidence.employment_document_id)
        return AdminReviewEvidenceResponse(
            **base.model_dump(),
            document_type=document.document_type if document is not None else None,
            original_filename=document.original_filename if document is not None else None,
            mime_type=document.content_type if document is not None else None,
            file_size=document.byte_size if document is not None else None,
            upload_status=document.verification_status if document is not None else None,
        )

    @staticmethod
    def _to_admin_contact_response(contact) -> AdminVerificationContactResponse:  # noqa: ANN001
        return AdminVerificationContactResponse(
            public_id=contact.public_id,
            contact_name=contact.contact_name,
            contact_email=contact.contact_email,
            contact_role=contact.contact_role,
            contact_type=normalize_contact_type(contact.contact_type),
            candidate_note=contact.candidate_note,
            review_status=normalize_contact_review_status(contact.review_status),
            review_notes=contact.review_notes,
            reviewed_by_user_id=contact.reviewed_by_user_id,
            reviewed_at=contact.reviewed_at,
            superseded_at=contact.superseded_at,
            created_at=contact.created_at,
            updated_at=contact.updated_at,
        )

    @staticmethod
    def _to_internal_note_response(note, review_public_ids) -> AdminReviewInternalNoteResponse:  # noqa: ANN001
        return AdminReviewInternalNoteResponse(
            public_id=note.public_id,
            review_public_id=review_public_ids[note.verification_request_review_id],
            author_user_id=note.author_user_id,
            visibility=note.visibility,
            note_type=note.note_type,
            body=note.body,
            metadata=dict(note.metadata_payload or {}),
            created_at=note.created_at,
            updated_at=note.updated_at,
        )

    async def assign(
        self,
        actor_user_id: UUID,
        verification_request_public_id: UUID,
        payload: AdminReviewAssignRequest,
    ) -> AdminReviewWorkflowEnvelope:
        request = await self._require_admin_reviewable_request(verification_request_public_id)
        assignee = await self._users.get_by_id(payload.assignee_user_id)
        if assignee is None:
            raise NotFoundError("Assignee user not found")
        if not has_permission(assignee.role, Permission.REVIEW_VERIFICATION):
            raise ForbiddenError("Assignee does not have admin review permissions")

        review = await self._get_or_create_review(request, actor_user_id)
        event_type = "verification_request_review_assigned"
        if review.assigned_reviewer_user_id is not None and review.assigned_reviewer_user_id != payload.assignee_user_id:
            event_type = "verification_request_review_reassigned"
        review.assigned_reviewer_user_id = payload.assignee_user_id
        review.assigned_by_user_id = actor_user_id
        review.assigned_at = datetime.now(tz=UTC)
        review.review_status = VerificationRequestReviewStatus.ASSIGNED
        await self._workflow.record_action(
            request,
            actor_user_id=actor_user_id,
            event_type=event_type,
            event_source=VerificationRequestEventSource.ADMIN,
            metadata={
                "review_public_id": str(review.public_id),
                "assignee_user_id": str(payload.assignee_user_id),
            },
        )
        await self._session.commit()
        refreshed_review = await self._reviews.get_review_by_public_id(review.public_id)
        if refreshed_review is None:
            raise NotFoundError("Verification request review not found")
        return AdminReviewWorkflowEnvelope(
            request=self._to_request_response(request),
            review=self._to_review_response(refreshed_review),
        )

    async def add_note(
        self,
        actor_user_id: UUID,
        verification_request_public_id: UUID,
        payload: AdminReviewNoteCreateRequest,
    ) -> AdminReviewNoteResponse:
        request = await self._get_required_request(verification_request_public_id)
        review = await self._get_or_create_review(request, actor_user_id)
        if review.review_status in {VerificationRequestReviewStatus.PENDING, VerificationRequestReviewStatus.ASSIGNED}:
            review.review_status = VerificationRequestReviewStatus.IN_REVIEW

        note = VerificationReviewNote(
            verification_request_review_id=review.id,
            author_user_id=actor_user_id,
            visibility=payload.visibility,
            note_type=payload.note_type,
            body=payload.body,
            metadata_payload=payload.metadata,
        )
        await self._reviews.create_note(note)
        await self._workflow.record_action(
            request,
            actor_user_id=actor_user_id,
            event_type="verification_request_admin_note_added",
            event_source=VerificationRequestEventSource.ADMIN,
            metadata={
                "review_public_id": str(review.public_id),
                "note_public_id": str(note.public_id),
                "visibility": payload.visibility.value,
                "note_type": payload.note_type.value,
            },
        )
        await self._session.commit()
        return self._to_note_response(note)

    async def request_corrections(
        self,
        actor_user_id: UUID,
        verification_request_public_id: UUID,
        payload: AdminReviewCorrectionRequest,
    ) -> VerificationRequestResponse:
        request = await self._require_admin_reviewable_request(verification_request_public_id)
        review = await self._get_or_create_review(request, actor_user_id)
        review.review_status = VerificationRequestReviewStatus.CORRECTIONS_REQUESTED

        for item in payload.corrections:
            evidence = None
            if item.evidence_public_id is not None:
                evidence = await self._evidence.get_by_public_id(item.evidence_public_id)
                if evidence is None or evidence.verification_request_id != request.id:
                    raise NotFoundError("Verification request evidence not found")
                evidence.status = VerificationRequestEvidenceStatus.NEEDS_CORRECTION

            correction = VerificationReviewCorrection(
                verification_request_review_id=review.id,
                verification_request_evidence_id=evidence.id if evidence is not None else None,
                requested_by_user_id=actor_user_id,
                status=VerificationReviewCorrectionStatus.OPEN,
                field_key=item.field_key,
                request_text=item.request_text,
                guidance=item.guidance,
            )
            await self._reviews.create_correction(correction)

            if item.field_key.startswith("verification_contact"):
                contact = await self._contacts.get_current(request.id)
                if contact is not None:
                    contact.review_status = VerificationContactReviewStatus.CHANGES_REQUESTED
                    contact.review_notes = item.request_text
                    contact.reviewed_by_user_id = actor_user_id
                    contact.reviewed_at = datetime.now(tz=UTC)

        await self._workflow.transition(
            request,
            target_status=VerificationRequestStatus.AWAITING_SUBJECT_CORRECTIONS,
            actor_user_id=actor_user_id,
            event_type="admin_requested_corrections",
            event_source=VerificationRequestEventSource.ADMIN,
            metadata={"corrections_count": len(payload.corrections)},
        )
        await self._session.commit()
        refreshed = await self._requests.get_by_public_id(request.public_id)
        if refreshed is None:
            raise NotFoundError("Verification request not found")
        return self._to_request_response(refreshed)

    async def approve(
        self,
        actor_user_id: UUID,
        verification_request_public_id: UUID,
        payload: AdminReviewDecisionRequest,
    ) -> VerificationRequestResponse:
        request = await self._require_admin_reviewable_request(verification_request_public_id)
        review = await self._get_or_create_review(request, actor_user_id)
        review.review_status = VerificationRequestReviewStatus.APPROVED
        review.decision_by_user_id = actor_user_id
        review.decision_at = datetime.now(tz=UTC)
        review.decision_summary = payload.decision_summary

        for evidence in await self._evidence.list_for_request(request.id):
            if evidence.status in {
                VerificationRequestEvidenceStatus.SUBMITTED,
                VerificationRequestEvidenceStatus.UNDER_REVIEW,
                VerificationRequestEvidenceStatus.NEEDS_CORRECTION,
            }:
                evidence.status = VerificationRequestEvidenceStatus.ACCEPTED
        contact = await self._contacts.get_current(request.id)
        if request.employment_id is not None and contact is None:
            raise ConflictError("Employment verification requires a verification contact")
        if contact is not None and contact.review_status != VerificationContactReviewStatus.APPROVED:
            raise ConflictError("Verification contact must be approved before approving the request")

        request.approved_for_organization_verification_at = datetime.now(tz=UTC)
        await self._workflow.transition(
            request,
            target_status=VerificationRequestStatus.APPROVED_FOR_ORGANIZATION_VERIFICATION,
            actor_user_id=actor_user_id,
            event_type="admin_approved",
            event_source=VerificationRequestEventSource.ADMIN,
            metadata={"decision_summary": payload.decision_summary},
        )
        await self._advance_to_organization_stage(request, actor_user_id=actor_user_id)
        await self._session.commit()
        refreshed = await self._requests.get_by_public_id(request.public_id)
        if refreshed is None:
            raise NotFoundError("Verification request not found")
        return self._to_request_response(refreshed)

    async def review_contact(
        self,
        actor_user_id: UUID,
        verification_request_public_id: UUID,
        payload: AdminVerificationContactReviewRequest,
    ) -> VerificationContactResponse:
        request = await self._require_admin_reviewable_request(verification_request_public_id)
        contact = await self._contacts.get_current(request.id)
        if contact is None:
            raise NotFoundError("Verification contact not found")
        contact.review_status = payload.review_status
        contact.review_notes = payload.review_notes
        contact.reviewed_by_user_id = actor_user_id
        contact.reviewed_at = datetime.now(tz=UTC)
        await self._workflow.record_action(
            request,
            actor_user_id=actor_user_id,
            event_type="verification_contact_reviewed",
            event_source=VerificationRequestEventSource.ADMIN,
            metadata={
                "verification_contact_public_id": str(contact.public_id),
                "review_status": payload.review_status.value,
            },
        )
        await self._session.commit()
        await self._session.refresh(contact)
        from app.services.verification_request_service import VerificationRequestService

        return VerificationRequestService(self._session)._to_contact_response(contact)

    async def reject(
        self,
        actor_user_id: UUID,
        verification_request_public_id: UUID,
        payload: AdminReviewDecisionRequest,
    ) -> VerificationRequestResponse:
        request = await self._require_admin_reviewable_request(verification_request_public_id)
        review = await self._get_or_create_review(request, actor_user_id)
        review.review_status = VerificationRequestReviewStatus.REJECTED
        review.decision_by_user_id = actor_user_id
        review.decision_at = datetime.now(tz=UTC)
        review.decision_summary = payload.decision_summary

        await self._workflow.transition(
            request,
            target_status=VerificationRequestStatus.REJECTED,
            actor_user_id=actor_user_id,
            event_type="verification_request_admin_rejected",
            event_source=VerificationRequestEventSource.ADMIN,
            metadata={"decision_summary": payload.decision_summary},
        )
        await self._session.commit()
        refreshed = await self._requests.get_by_public_id(request.public_id)
        if refreshed is None:
            raise NotFoundError("Verification request not found")
        return self._to_request_response(refreshed)

    async def resolve_organization(
        self,
        actor_user_id: UUID,
        verification_request_public_id: UUID,
        payload: AdminReviewOrganizationResolutionRequest,
    ) -> VerificationRequestResponse:
        request = await self._get_required_request(verification_request_public_id)
        if request.status not in {
            VerificationRequestStatus.PENDING_ORGANIZATION_RESOLUTION,
            VerificationRequestStatus.APPROVED_FOR_ORGANIZATION_VERIFICATION,
        }:
            raise ConflictError("Verification request is not awaiting organization resolution")

        organization = await self._organizations.get_by_public_id(payload.organization_public_id)
        if organization is None:
            raise NotFoundError("Organization not found")

        request.organization_id = organization.id
        request.target_organization_name = organization.name
        await self._advance_to_organization_stage(
            request,
            actor_user_id=actor_user_id,
            resolved_organization_public_id=organization.public_id,
        )
        await self._session.commit()
        refreshed = await self._requests.get_by_public_id(request.public_id)
        if refreshed is None:
            raise NotFoundError("Verification request not found")
        return self._to_request_response(refreshed)

    async def get_timeline(
        self,
        verification_request_public_id: UUID,
        params: ListQueryParams | None = None,
    ) -> AdminReviewTimelineResponse:
        request = await self._get_required_request(verification_request_public_id)
        rows = await self._requests.list_timeline(request.id)
        timeline_items = [
            VerificationRequestTimelineEventResponse(
                public_id=row.public_id,
                event_type=row.event_type,
                event_source=row.event_source,
                previous_status=row.previous_status,
                new_status=row.new_status,
                metadata=row.metadata_payload,
                created_at=row.created_at,
            )
            for row in rows
        ]
        page = filter_sort_paginate(
            timeline_items,
            params=params or ListQueryParams(),
            search_fields=("event_type", "event_source"),
            status_field=None,
            allowed_sort_fields=("created_at", "event_type"),
            default_sort_by="created_at",
            force_page_envelope=True,
        )
        if not isinstance(page, Page):
            raise RuntimeError("Admin review timeline must return a page envelope")
        return AdminReviewTimelineResponse(
            timeline=VerificationRequestTimelineResponse(
                verification_request_public_id=request.public_id,
                items=page.items,
                total=page.total,
                page=page.page,
                page_size=page.page_size,
                total_pages=page.total_pages,
                offset=page.offset,
                limit=page.limit,
            )
        )

    async def _require_admin_reviewable_request(self, verification_request_public_id: UUID):
        request = await self._get_required_request(verification_request_public_id)
        if request.status not in {
            VerificationRequestStatus.PENDING_ADMIN_REVIEW,
            VerificationRequestStatus.PENDING_ADMIN_RE_REVIEW,
        }:
            raise ConflictError("Verification request is not awaiting admin review")
        return request

    async def _get_required_request(self, verification_request_public_id: UUID):
        request = await self._requests.get_by_public_id(verification_request_public_id)
        if request is None:
            raise NotFoundError("Verification request not found")
        return request

    async def _get_or_create_review(
        self,
        request,
        actor_user_id: UUID,
    ) -> VerificationRequestReview:
        latest = await self._reviews.get_latest_review_for_request(request.id)
        if latest is None or self._should_start_new_review_round(request.status, latest.review_status):
            review = VerificationRequestReview(
                verification_request_id=request.id,
                review_round=await self._reviews.get_next_review_round(request.id),
                review_status=VerificationRequestReviewStatus.PENDING,
                assigned_reviewer_user_id=actor_user_id,
                assigned_by_user_id=actor_user_id,
                assigned_at=datetime.now(tz=UTC),
            )
            return await self._reviews.create_review(review)
        return latest

    def _should_start_new_review_round(
        self,
        request_status: VerificationRequestStatus,
        review_status: VerificationRequestReviewStatus,
    ) -> bool:
        return (
            request_status == VerificationRequestStatus.PENDING_ADMIN_RE_REVIEW
            and review_status == VerificationRequestReviewStatus.CORRECTIONS_REQUESTED
        ) or review_status in {
            VerificationRequestReviewStatus.APPROVED,
            VerificationRequestReviewStatus.REJECTED,
            VerificationRequestReviewStatus.CANCELLED,
        }

    async def _advance_to_organization_stage(
        self,
        request,
        *,
        actor_user_id: UUID,
        resolved_organization_public_id: UUID | None = None,
    ) -> None:
        metadata: dict[str, str] = {}
        if resolved_organization_public_id is not None:
            metadata["organization_public_id"] = str(resolved_organization_public_id)

        if request.organization_id is None:
            await self._workflow.transition(
                request,
                target_status=VerificationRequestStatus.PENDING_ORGANIZATION_RESOLUTION,
                actor_user_id=actor_user_id,
                event_type="verification_request_organization_resolution_required",
                event_source=VerificationRequestEventSource.SYSTEM,
                metadata=metadata,
            )
            return

        contact = await self._contacts.get_current(request.id)
        if request.employment_id is not None:
            if contact is None or contact.review_status != VerificationContactReviewStatus.APPROVED:
                raise ConflictError("An approved verification contact is required for employer outreach")
            await self._employer_outreach.initiate_admin_outreach(
                actor_user_id=actor_user_id,
                verification_request=request,
                payload=EmployerVerificationRequestBody(
                    contact_name=contact.contact_name or contact.contact_role or normalize_contact_type(contact.contact_type),
                    verifier_email=contact.contact_email,
                    relationship=contact.contact_role or normalize_contact_type(contact.contact_type),
                ),
            )
        request.organization_outreach_sent_at = datetime.now(tz=UTC)
        await self._workflow.transition(
            request,
            target_status=VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE,
            actor_user_id=actor_user_id,
            event_type="organization_resolved",
            event_source=VerificationRequestEventSource.SYSTEM,
            metadata=metadata,
        )

    def _to_request_response(self, request) -> VerificationRequestResponse:  # noqa: ANN001
        from app.services.verification_request_service import VerificationRequestService

        return VerificationRequestService(self._session)._to_response(request)

    def _to_evidence_response(self, evidence) -> VerificationRequestEvidenceResponse:  # noqa: ANN001
        from app.services.verification_request_service import VerificationRequestService

        return VerificationRequestService(self._session)._to_evidence_response(evidence)

    def _to_correction_response(self, correction) -> VerificationRequestCorrectionResponse:  # noqa: ANN001
        from app.services.verification_request_service import VerificationRequestService

        return VerificationRequestService(self._session)._to_correction_response(correction)

    def _to_review_response(self, review: VerificationRequestReview) -> AdminReviewCycleResponse:
        return AdminReviewCycleResponse(
            public_id=review.public_id,
            review_round=review.review_round,
            review_status=review.review_status,
            assigned_reviewer_user_id=review.assigned_reviewer_user_id,
            assigned_by_user_id=review.assigned_by_user_id,
            assigned_at=review.assigned_at,
            decision_by_user_id=review.decision_by_user_id,
            decision_at=review.decision_at,
            decision_summary=review.decision_summary,
            created_at=review.created_at,
            updated_at=review.updated_at,
        )

    def _to_note_response(self, note: VerificationReviewNote) -> AdminReviewNoteResponse:
        return AdminReviewNoteResponse(
            public_id=note.public_id,
            visibility=note.visibility,
            note_type=note.note_type,
            body=note.body,
            metadata=note.metadata_payload,
            created_at=note.created_at,
            updated_at=note.updated_at,
        )
