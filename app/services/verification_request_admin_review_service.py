"""Admin review workflow for verification requests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.admin_review.enums import (
    VerificationRequestEvidenceStatus,
    VerificationRequestReviewStatus,
    VerificationReviewCorrectionStatus,
)
from app.core.permissions import Permission, has_permission
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.verification_request_review import VerificationRequestReview
from app.models.verification_review_correction import VerificationReviewCorrection
from app.models.verification_review_note import VerificationReviewNote
from app.repositories.organization import OrganizationRepository
from app.repositories.user import UserRepository
from app.repositories.verification_request import VerificationRequestRepository
from app.repositories.verification_request_evidence import VerificationRequestEvidenceRepository
from app.repositories.verification_request_review import VerificationRequestReviewRepository
from app.schemas.pagination import ListQueryParams, Page, filter_sort_paginate
from app.schemas.admin_review_workflow import (
    AdminReviewAssignRequest,
    AdminReviewCorrectionRequest,
    AdminReviewCycleResponse,
    AdminReviewDecisionRequest,
    AdminReviewDetailResponse,
    AdminReviewNoteCreateRequest,
    AdminReviewNoteResponse,
    AdminReviewOrganizationResolutionRequest,
    AdminReviewQueueResponse,
    AdminReviewTimelineResponse,
    AdminReviewWorkflowEnvelope,
)
from app.schemas.verification_request import (
    VerificationRequestCorrectionResponse,
    VerificationRequestEvidenceResponse,
    VerificationRequestResponse,
    VerificationRequestTimelineEventResponse,
    VerificationRequestTimelineResponse,
)
from app.services.verification_request_workflow_service import VerificationRequestWorkflowService
from app.verification_requests.enums import VerificationRequestEventSource, VerificationRequestStatus


class VerificationRequestAdminReviewService:
    """Platform-admin review stage for canonical verification requests."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._requests = VerificationRequestRepository(session)
        self._organizations = OrganizationRepository(session)
        self._users = UserRepository(session)
        self._evidence = VerificationRequestEvidenceRepository(session)
        self._reviews = VerificationRequestReviewRepository(session)
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
            items=page.items,
            total=page.total,
            page=page.page,
            page_size=page.page_size,
            total_pages=page.total_pages,
            offset=page.offset,
            limit=page.limit,
        )

    async def get_detail(self, verification_request_public_id: UUID) -> AdminReviewDetailResponse:
        request = await self._get_required_request(verification_request_public_id)
        evidence_items = await self._evidence.list_for_request(request.id)
        reviews = await self._reviews.list_reviews_for_request(request.id)
        open_corrections = await self._reviews.list_open_corrections_for_request([review.id for review in reviews])
        return AdminReviewDetailResponse(
            request=self._to_request_response(request),
            evidence=[self._to_evidence_response(item) for item in evidence_items],
            reviews=[self._to_review_response(review) for review in reviews],
            open_corrections=[self._to_correction_response(item) for item in open_corrections],
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

        await self._workflow.transition(
            request,
            target_status=VerificationRequestStatus.AWAITING_SUBJECT_CORRECTIONS,
            actor_user_id=actor_user_id,
            event_type="verification_request_corrections_requested",
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

        request.approved_for_organization_verification_at = datetime.now(tz=UTC)
        await self._workflow.transition(
            request,
            target_status=VerificationRequestStatus.APPROVED_FOR_ORGANIZATION_VERIFICATION,
            actor_user_id=actor_user_id,
            event_type="verification_request_admin_approved",
            event_source=VerificationRequestEventSource.ADMIN,
            metadata={"decision_summary": payload.decision_summary},
        )
        await self._advance_to_organization_stage(request, actor_user_id=actor_user_id)
        await self._session.commit()
        refreshed = await self._requests.get_by_public_id(request.public_id)
        if refreshed is None:
            raise NotFoundError("Verification request not found")
        return self._to_request_response(refreshed)

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

        request.organization_outreach_sent_at = datetime.now(tz=UTC)
        await self._workflow.transition(
            request,
            target_status=VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE,
            actor_user_id=actor_user_id,
            event_type="verification_request_organization_outreach_initiated",
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
