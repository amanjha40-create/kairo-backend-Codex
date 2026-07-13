"""Verification request engine use cases."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.admin_review.enums import VerificationRequestEvidenceStatus, VerificationReviewCorrectionStatus
from app.exceptions import ConflictError, ForbiddenError, NotFoundError, ServiceUnavailableError
from app.models.trust_invitation import TrustInvitation
from app.models.user import User
from app.models.verification_request import VerificationRequest
from app.models.verification_request_evidence import VerificationRequestEvidence
from app.notifications.contracts import NotificationRequest
from app.repositories.organization import OrganizationRepository
from app.repositories.trust_invitation import TrustInvitationRepository
from app.repositories.user import UserRepository
from app.repositories.user_document import UserDocumentRepository
from app.repositories.verification_request import VerificationRequestRepository
from app.repositories.verification_request_evidence import VerificationRequestEvidenceRepository
from app.repositories.verification_request_review import VerificationRequestReviewRepository
from app.schemas.pagination import ListQueryParams, Page, filter_sort_paginate
from app.schemas.verification_request import (
    SubjectVerificationRequestCreateRequest,
    VerificationRequestActionPayload,
    VerificationRequestCorrectionResponse,
    VerificationRequestCreateRequest,
    VerificationRequestEvidenceCreateRequest,
    VerificationRequestEvidenceResponse,
    VerificationRequestEvidenceUpdateRequest,
    VerificationRequestResponse,
    VerificationRequestTimelineEventResponse,
    VerificationRequestTimelineResponse,
)
from app.services.notification_service import NotificationService
from app.services.connector_execution_service import ConnectorExecutionService
from app.services.connector_registry_service import ConnectorRegistryService
from app.services.connector_result_normalizer import ConnectorResultNormalizer
from app.services.connector_selection_service import ConnectorSelectionService
from app.services.verification_request_workflow_service import VerificationRequestWorkflowService
from app.verification_connectors.enums import VerificationConnectorResultStatus
from app.verification_requests.enums import (
    VerificationRequestEventSource,
    VerificationRequestOriginType,
    VerificationRequestStatus,
)

logger = logging.getLogger(__name__)


class VerificationRequestService:
    """Canonical request management and authorization for verification workflows."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        notifications: NotificationService | None = None,
    ) -> None:
        self._session = session
        self._requests = VerificationRequestRepository(session)
        self._organizations = OrganizationRepository(session)
        self._users = UserRepository(session)
        self._user_documents = UserDocumentRepository(session)
        self._trust_invitations = TrustInvitationRepository(session)
        self._evidence = VerificationRequestEvidenceRepository(session)
        self._reviews = VerificationRequestReviewRepository(session)
        self._workflow = VerificationRequestWorkflowService(self._requests)
        self._connector_registry = ConnectorRegistryService(session)
        self._connector_selector = ConnectorSelectionService(self._connector_registry)
        self._connector_normalizer = ConnectorResultNormalizer()
        self._connector_executor = ConnectorExecutionService(
            session,
            self._connector_registry,
            self._connector_normalizer,
        )
        self._notifications = notifications or NotificationService(session)

    async def create(
        self,
        actor_user_id: UUID,
        organization_public_id: UUID,
        payload: VerificationRequestCreateRequest,
    ) -> VerificationRequestResponse:
        organization = await self._require_organization_member(actor_user_id, organization_public_id)
        subject_name, subject_email, subject_user_id, trust_invitation = await self._resolve_subject_details(
            organization_id=organization.id,
            payload=payload,
        )
        status = VerificationRequestStatus.PENDING_SUBJECT_ACCEPTANCE
        origin_type = VerificationRequestOriginType.ORGANIZATION_CREATED
        if trust_invitation is not None:
            origin_type = VerificationRequestOriginType.TRUST_INVITATION
            if trust_invitation.accepted_at is not None or trust_invitation.accepted_by_user_id is not None:
                status = VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION

        request = VerificationRequest(
            origin_type=origin_type,
            organization_id=organization.id,
            subject_user_id=subject_user_id,
            trust_invitation_id=trust_invitation.id if trust_invitation is not None else None,
            subject_name=subject_name,
            subject_email=subject_email,
            target_organization_name=organization.name,
            request_type=payload.request_type,
            status=status,
            requested_by_user_id=actor_user_id,
            due_date=payload.due_date,
            trust_context=payload.trust_context,
        )
        await self._requests.create(request)
        await self._workflow.record_creation(
            request,
            actor_user_id=actor_user_id,
            event_source=VerificationRequestEventSource.ORGANIZATION,
            metadata={
                "request_type": payload.request_type.value,
                "origin_type": origin_type.value,
            },
        )
        await self._session.commit()
        await self._session.refresh(request)
        refreshed = await self._requests.get_by_public_id(request.public_id)
        if refreshed is None:
            raise NotFoundError("Verification request not found")
        return self._to_response(refreshed)

    async def create_subject_request(
        self,
        actor_user_id: UUID,
        payload: SubjectVerificationRequestCreateRequest,
    ) -> VerificationRequestResponse:
        subject = await self._require_subject_user(actor_user_id)
        organization = None
        target_name = payload.target_organization_name
        target_email = self._normalize_email(str(payload.target_organization_email)) if payload.target_organization_email else None
        if payload.organization_public_id is not None:
            organization = await self._organizations.get_by_public_id(payload.organization_public_id)
            if organization is None:
                raise NotFoundError("Organization not found")
            target_name = target_name or organization.name

        request = VerificationRequest(
            origin_type=VerificationRequestOriginType.SUBJECT_INITIATED,
            organization_id=organization.id if organization is not None else None,
            subject_user_id=subject.id,
            subject_name=self._subject_name(subject),
            subject_email=subject.email,
            target_organization_name=target_name,
            target_organization_email=target_email,
            request_type=payload.request_type,
            status=VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION,
            requested_by_user_id=actor_user_id,
            due_date=payload.due_date,
            trust_context=payload.trust_context,
        )
        await self._requests.create(request)
        await self._workflow.record_creation(
            request,
            actor_user_id=actor_user_id,
            event_source=VerificationRequestEventSource.CANDIDATE,
            metadata={
                "request_type": payload.request_type.value,
                "origin_type": VerificationRequestOriginType.SUBJECT_INITIATED.value,
            },
        )
        await self._session.commit()
        await self._session.refresh(request)
        refreshed = await self._requests.get_by_public_id(request.public_id)
        if refreshed is None:
            raise NotFoundError("Verification request not found")
        return self._to_response(refreshed)

    async def list_mine(
        self,
        actor_user_id: UUID,
        params: ListQueryParams | None = None,
    ) -> list[VerificationRequestResponse] | Page[VerificationRequestResponse]:
        items = await self._requests.list_for_subject(actor_user_id)
        responses = [self._to_response(item) for item in items]
        if params is None:
            return responses
        return self._filter_request_responses(responses, params)

    async def list_for_organization(
        self,
        actor_user_id: UUID,
        organization_public_id: UUID,
        params: ListQueryParams | None = None,
    ) -> list[VerificationRequestResponse] | Page[VerificationRequestResponse]:
        organization = await self._require_organization_member(actor_user_id, organization_public_id)
        items = await self._requests.list_for_organization(organization.id)
        responses = [self._to_response(item) for item in items]
        if params is None:
            return responses
        return self._filter_request_responses(responses, params)

    async def get_detail(
        self,
        actor_user_id: UUID,
        actor_email: str,
        verification_request_public_id: UUID,
    ) -> VerificationRequestResponse:
        request = await self._get_accessible_request(
            actor_user_id=actor_user_id,
            actor_email=actor_email,
            verification_request_public_id=verification_request_public_id,
        )
        return self._to_response(request)

    async def accept(
        self,
        actor_user_id: UUID,
        actor_email: str,
        verification_request_public_id: UUID,
    ) -> VerificationRequestResponse:
        request = await self._get_required_request(verification_request_public_id)
        if not self._is_subject_actor(request, actor_user_id, actor_email):
            membership = await self._get_membership_for_request(request, actor_user_id)
            if membership is not None:
                raise ForbiddenError("Only the request subject can accept this verification request")
            raise NotFoundError("Verification request not found")

        if request.subject_user_id is None:
            request.subject_user_id = actor_user_id
        await self._workflow.transition(
            request,
            target_status=VerificationRequestStatus.ACCEPTED,
            actor_user_id=actor_user_id,
            event_type="verification_request_subject_accepted",
            event_source=VerificationRequestEventSource.CANDIDATE,
            metadata={},
        )
        await self._session.commit()
        await self._session.refresh(request)
        refreshed = await self._requests.get_by_public_id(request.public_id)
        if refreshed is None:
            raise NotFoundError("Verification request not found")
        return self._to_response(refreshed)

    async def list_evidence(
        self,
        actor_user_id: UUID,
        actor_email: str,
        verification_request_public_id: UUID,
        params: ListQueryParams | None = None,
    ) -> list[VerificationRequestEvidenceResponse] | Page[VerificationRequestEvidenceResponse]:
        request = await self._require_subject_request(actor_user_id, actor_email, verification_request_public_id)
        items = await self._evidence.list_for_request(request.id)
        responses = [self._to_evidence_response(item) for item in items]
        if params is None:
            return responses
        return filter_sort_paginate(
            responses,
            params=params,
            search_fields=("evidence_type", "field_key", "status"),
            allowed_sort_fields=("created_at", "updated_at", "evidence_type", "field_key", "status"),
            default_sort_by="created_at",
        )

    async def add_evidence(
        self,
        actor_user_id: UUID,
        actor_email: str,
        verification_request_public_id: UUID,
        payload: VerificationRequestEvidenceCreateRequest,
    ) -> VerificationRequestEvidenceResponse:
        request = await self._require_editable_subject_request(actor_user_id, actor_email, verification_request_public_id)
        if payload.document_id is not None:
            document = await self._user_documents.get_owned(payload.document_id, actor_user_id)
            if document is None:
                raise NotFoundError("User document not found")

        evidence = VerificationRequestEvidence(
            verification_request_id=request.id,
            submitted_by_user_id=actor_user_id,
            evidence_type=payload.evidence_type.strip().lower(),
            field_key=payload.field_key.strip(),
            document_id=payload.document_id,
            value=payload.value,
            status=VerificationRequestEvidenceStatus.SUBMITTED,
        )
        await self._evidence.create(evidence)
        await self._workflow.record_action(
            request,
            actor_user_id=actor_user_id,
            event_type="verification_request_evidence_added",
            event_source=VerificationRequestEventSource.CANDIDATE,
            metadata={
                "evidence_public_id": str(evidence.public_id),
                "field_key": evidence.field_key,
                "evidence_type": evidence.evidence_type,
            },
        )
        await self._session.commit()
        await self._session.refresh(evidence)
        refreshed = await self._evidence.get_by_public_id(evidence.public_id)
        if refreshed is None:
            raise NotFoundError("Verification request evidence not found")
        return self._to_evidence_response(refreshed)

    async def update_evidence(
        self,
        actor_user_id: UUID,
        actor_email: str,
        verification_request_public_id: UUID,
        evidence_public_id: UUID,
        payload: VerificationRequestEvidenceUpdateRequest,
    ) -> VerificationRequestEvidenceResponse:
        request = await self._require_editable_subject_request(actor_user_id, actor_email, verification_request_public_id)
        evidence = await self._evidence.get_by_public_id(evidence_public_id)
        if evidence is None or evidence.verification_request_id != request.id:
            raise NotFoundError("Verification request evidence not found")
        if evidence.submitted_by_user_id != actor_user_id and request.subject_user_id != actor_user_id:
            raise ForbiddenError("Only the request subject can update evidence")
        if payload.document_id is not None:
            document = await self._user_documents.get_owned(payload.document_id, actor_user_id)
            if document is None:
                raise NotFoundError("User document not found")

        if payload.evidence_type is not None:
            evidence.evidence_type = payload.evidence_type.strip().lower()
        if payload.field_key is not None:
            evidence.field_key = payload.field_key.strip()
        if payload.document_id is not None:
            evidence.document_id = payload.document_id
        if payload.value is not None:
            evidence.value = payload.value
        evidence.status = VerificationRequestEvidenceStatus.SUBMITTED
        await self._workflow.record_action(
            request,
            actor_user_id=actor_user_id,
            event_type="verification_request_evidence_updated",
            event_source=VerificationRequestEventSource.CANDIDATE,
            metadata={
                "evidence_public_id": str(evidence.public_id),
                "field_key": evidence.field_key,
                "evidence_type": evidence.evidence_type,
            },
        )
        await self._session.commit()
        refreshed = await self._evidence.get_by_public_id(evidence.public_id)
        if refreshed is None:
            raise NotFoundError("Verification request evidence not found")
        return self._to_evidence_response(refreshed)

    async def submit_for_review(
        self,
        actor_user_id: UUID,
        actor_email: str,
        verification_request_public_id: UUID,
    ) -> VerificationRequestResponse:
        request = await self._require_subject_request(actor_user_id, actor_email, verification_request_public_id)
        if request.status not in {
            VerificationRequestStatus.ACCEPTED,
            VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION,
        }:
            raise ConflictError("Verification request cannot be submitted for review in its current status")
        evidence_items = await self._evidence.list_for_request(request.id)
        if not evidence_items:
            raise ConflictError("Add at least one evidence item before submitting for review")
        request.submitted_for_admin_review_at = datetime.now(tz=UTC)
        await self._workflow.transition(
            request,
            target_status=VerificationRequestStatus.PENDING_ADMIN_REVIEW,
            actor_user_id=actor_user_id,
            event_type="verification_request_submitted_for_admin_review",
            event_source=VerificationRequestEventSource.CANDIDATE,
            metadata={"evidence_count": len(evidence_items)},
        )
        return await self._commit_and_reload(request.public_id)

    async def list_corrections(
        self,
        actor_user_id: UUID,
        actor_email: str,
        verification_request_public_id: UUID,
        params: ListQueryParams | None = None,
    ) -> list[VerificationRequestCorrectionResponse] | Page[VerificationRequestCorrectionResponse]:
        request = await self._require_subject_request(actor_user_id, actor_email, verification_request_public_id)
        review_ids = [review.id for review in await self._reviews.list_reviews_for_request(request.id)]
        corrections = await self._reviews.list_open_corrections_for_request(review_ids)
        responses = [self._to_correction_response(item) for item in corrections]
        if params is None:
            return responses
        return filter_sort_paginate(
            responses,
            params=params,
            search_fields=("field_key", "request_text", "status"),
            allowed_sort_fields=("created_at", "updated_at", "field_key", "status"),
            default_sort_by="created_at",
        )

    async def resubmit(
        self,
        actor_user_id: UUID,
        actor_email: str,
        verification_request_public_id: UUID,
    ) -> VerificationRequestResponse:
        request = await self._require_subject_request(actor_user_id, actor_email, verification_request_public_id)
        if request.status != VerificationRequestStatus.AWAITING_SUBJECT_CORRECTIONS:
            raise ConflictError("Verification request is not awaiting subject corrections")
        review_ids = [review.id for review in await self._reviews.list_reviews_for_request(request.id)]
        corrections = await self._reviews.list_open_corrections_for_request(review_ids)
        if not corrections:
            raise ConflictError("There are no open correction requests to resolve")
        for correction in corrections:
            correction.status = VerificationReviewCorrectionStatus.RESOLVED
            correction.resolved_by_user_id = actor_user_id
            correction.resolved_at = datetime.now(tz=UTC)
        request.last_subject_resubmitted_at = datetime.now(tz=UTC)
        await self._workflow.transition(
            request,
            target_status=VerificationRequestStatus.PENDING_ADMIN_RE_REVIEW,
            actor_user_id=actor_user_id,
            event_type="verification_request_resubmitted",
            event_source=VerificationRequestEventSource.CANDIDATE,
            metadata={"resolved_correction_count": len(corrections)},
        )
        return await self._commit_and_reload(request.public_id)

    async def request_information(
        self,
        actor_user_id: UUID,
        verification_request_public_id: UUID,
        payload: VerificationRequestActionPayload,
    ) -> VerificationRequestResponse:
        request = await self._require_manageable_request(actor_user_id, verification_request_public_id)
        await self._transition_to_in_progress_if_needed(
            request,
            actor_user_id,
            payload.metadata,
            allowed_current_statuses={
                VerificationRequestStatus.ACCEPTED,
                VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE,
            },
        )
        await self._workflow.transition(
            request,
            target_status=VerificationRequestStatus.AWAITING_INFORMATION,
            actor_user_id=actor_user_id,
            event_type="verification_request_information_requested",
            event_source=VerificationRequestEventSource.ORGANIZATION,
            metadata=self._merge_note_metadata(payload),
        )
        return await self._commit_and_reload(request.public_id)

    async def verify(
        self,
        actor_user_id: UUID,
        verification_request_public_id: UUID,
        payload: VerificationRequestActionPayload,
    ) -> VerificationRequestResponse:
        request = await self._require_manageable_request(actor_user_id, verification_request_public_id)
        connector = await self._connector_selector.select_for_request(request)
        await self._transition_to_in_progress_if_needed(
            request,
            actor_user_id,
            payload.metadata,
            allowed_current_statuses={
                VerificationRequestStatus.ACCEPTED,
                VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE,
                VerificationRequestStatus.AWAITING_INFORMATION,
            },
        )
        await self._workflow.record_action(
            request,
            actor_user_id=actor_user_id,
            event_type="verification_connector_selected",
            event_source=VerificationRequestEventSource.SYSTEM,
            metadata={
                "connector_key": connector.connector_key,
                "connector_public_id": str(connector.public_id),
            },
        )
        try:
            run, result = await self._connector_executor.execute(
                connector=connector,
                request=request,
                actor_user_id=actor_user_id,
                metadata=payload.metadata,
            )
        except ServiceUnavailableError:
            await self._workflow.record_action(
                request,
                actor_user_id=actor_user_id,
                event_type="verification_connector_run_unavailable",
                event_source=VerificationRequestEventSource.SYSTEM,
                metadata={
                    "connector_key": connector.connector_key,
                },
            )
            await self._session.commit()
            raise
        except Exception:
            await self._workflow.record_action(
                request,
                actor_user_id=actor_user_id,
                event_type="verification_connector_run_failed",
                event_source=VerificationRequestEventSource.SYSTEM,
                metadata={
                    "connector_key": connector.connector_key,
                },
            )
            await self._session.commit()
            raise

        connector_metadata = {
            "connector_key": connector.connector_key,
            "connector_public_id": str(connector.public_id),
            "connector_run_public_id": str(run.public_id),
            "connector_result_status": result.status,
            "connector_confidence": result.confidence,
        }
        await self._workflow.record_action(
            request,
            actor_user_id=actor_user_id,
            event_type="verification_connector_run_completed",
            event_source=VerificationRequestEventSource.SYSTEM,
            metadata=connector_metadata,
        )
        final_metadata = {
            **self._merge_note_metadata(payload),
            **connector_metadata,
        }
        if result.status == VerificationConnectorResultStatus.VERIFIED.value:
            await self._workflow.transition(
                request,
                target_status=VerificationRequestStatus.VERIFIED,
                actor_user_id=actor_user_id,
                event_type="verification_request_verified",
                event_source=VerificationRequestEventSource.ORGANIZATION,
                metadata=final_metadata,
            )
            try:
                await self._notifications.create_and_dispatch(
                    NotificationRequest(
                        event_type="verification_completed",
                        recipient_user_id=request.subject_user_id,
                        recipient_email=request.subject_email,
                        payload={
                            "subject_name": request.subject_name,
                            "organization_name": self._organization_name(request),
                            "request_type": request.request_type.value,
                            "completed_at_iso": datetime.now(tz=UTC).isoformat(),
                        },
                        metadata={
                            "verification_request_public_id": str(request.public_id),
                            "organization_public_id": str(request.organization.public_id)
                            if request.organization is not None
                            else None,
                            "connector_run_public_id": str(run.public_id),
                        },
                    ),
                    actor_user_id=actor_user_id,
                )
            except Exception as exc:
                logger.warning(
                    "verification_completion_notification_failed",
                    extra={
                        "event": "verification_completion_notification_failed",
                        "verification_request_public_id": str(request.public_id),
                        "error_type": type(exc).__name__,
                    },
                )
        elif result.status == VerificationConnectorResultStatus.FAILED.value:
            await self._workflow.transition(
                request,
                target_status=VerificationRequestStatus.REJECTED,
                actor_user_id=actor_user_id,
                event_type="verification_request_rejected",
                event_source=VerificationRequestEventSource.ORGANIZATION,
                metadata=final_metadata,
            )
        else:
            await self._session.commit()
            raise ServiceUnavailableError("Verification connector is unavailable")
        return await self._commit_and_reload(request.public_id)

    async def reject(
        self,
        actor_user_id: UUID,
        verification_request_public_id: UUID,
        payload: VerificationRequestActionPayload,
    ) -> VerificationRequestResponse:
        request = await self._require_manageable_request(actor_user_id, verification_request_public_id)
        await self._transition_to_in_progress_if_needed(
            request,
            actor_user_id,
            payload.metadata,
            allowed_current_statuses={
                VerificationRequestStatus.ACCEPTED,
                VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE,
                VerificationRequestStatus.AWAITING_INFORMATION,
            },
        )
        await self._workflow.transition(
            request,
            target_status=VerificationRequestStatus.REJECTED,
            actor_user_id=actor_user_id,
            event_type="verification_request_rejected",
            event_source=VerificationRequestEventSource.ORGANIZATION,
            metadata=self._merge_note_metadata(payload),
        )
        return await self._commit_and_reload(request.public_id)

    async def cancel(
        self,
        actor_user_id: UUID,
        verification_request_public_id: UUID,
        payload: VerificationRequestActionPayload,
    ) -> VerificationRequestResponse:
        request = await self._require_manageable_request(actor_user_id, verification_request_public_id)
        await self._workflow.transition(
            request,
            target_status=VerificationRequestStatus.CANCELLED,
            actor_user_id=actor_user_id,
            event_type="verification_request_cancelled",
            event_source=VerificationRequestEventSource.ORGANIZATION,
            metadata=self._merge_note_metadata(payload),
        )
        return await self._commit_and_reload(request.public_id)

    async def get_timeline(
        self,
        actor_user_id: UUID,
        actor_email: str,
        verification_request_public_id: UUID,
        params: ListQueryParams | None = None,
    ) -> VerificationRequestTimelineResponse:
        request = await self._get_accessible_request(
            actor_user_id=actor_user_id,
            actor_email=actor_email,
            verification_request_public_id=verification_request_public_id,
        )
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
        effective_params = params or ListQueryParams()
        page = filter_sort_paginate(
            timeline_items,
            params=effective_params,
            search_fields=("event_type", "event_source"),
            status_field=None,
            allowed_sort_fields=("created_at", "event_type"),
            default_sort_by="created_at",
            force_page_envelope=True,
        )
        if not isinstance(page, Page):
            raise RuntimeError("Timeline pagination must return a page envelope")
        return VerificationRequestTimelineResponse(
            verification_request_public_id=request.public_id,
            items=page.items,
            total=page.total,
            page=page.page,
            page_size=page.page_size,
            total_pages=page.total_pages,
            offset=page.offset,
            limit=page.limit,
        )

    async def _commit_and_reload(self, request_public_id: UUID) -> VerificationRequestResponse:
        await self._session.commit()
        refreshed = await self._requests.get_by_public_id(request_public_id)
        if refreshed is None:
            raise NotFoundError("Verification request not found")
        return self._to_response(refreshed)

    async def _transition_to_in_progress_if_needed(
        self,
        request: VerificationRequest,
        actor_user_id: UUID,
        metadata: dict[str, object],
        *,
        allowed_current_statuses: set[VerificationRequestStatus],
    ) -> None:
        if request.status in allowed_current_statuses:
            await self._workflow.transition(
                request,
                target_status=VerificationRequestStatus.IN_PROGRESS,
                actor_user_id=actor_user_id,
                event_type="verification_request_started",
                event_source=VerificationRequestEventSource.ORGANIZATION,
                metadata=metadata,
            )

    async def _resolve_subject_details(
        self,
        *,
        organization_id: UUID,
        payload: VerificationRequestCreateRequest,
    ) -> tuple[str, str, UUID | None, TrustInvitation | None]:
        if payload.trust_invitation_public_id is not None:
            invitation = await self._trust_invitations.get_by_public_id(payload.trust_invitation_public_id)
            if invitation is None or invitation.organization_id != organization_id:
                raise NotFoundError("Trust invitation not found")
            if invitation.cancelled_at is not None:
                raise ConflictError("Cancelled trust invitations cannot seed verification requests")
            if invitation.expires_at <= datetime.now(tz=UTC):
                raise ConflictError("Expired trust invitations cannot seed verification requests")
            subject_user_id = invitation.accepted_by_user_id
            if subject_user_id is None:
                user = await self._users.get_by_email(invitation.subject_email)
                subject_user_id = user.id if user is not None and user.email_verified_at is not None else None
            return invitation.subject_name, invitation.subject_email, subject_user_id, invitation

        assert payload.subject_name is not None
        assert payload.subject_email is not None
        normalized_email = self._normalize_email(str(payload.subject_email))
        user = await self._users.get_by_email(normalized_email)
        subject_user_id = user.id if user is not None and user.email_verified_at is not None else None
        return payload.subject_name, normalized_email, subject_user_id, None

    async def _require_subject_user(self, actor_user_id: UUID) -> User:
        user = await self._users.get_by_id(actor_user_id)
        if user is None:
            raise NotFoundError("User not found")
        return user

    async def _require_organization_member(self, actor_user_id: UUID, organization_public_id: UUID):
        organization = await self._organizations.get_by_public_id(organization_public_id)
        if organization is None:
            raise NotFoundError("Organization not found")
        membership = await self._organizations.get_membership(organization.id, actor_user_id)
        if membership is None:
            raise NotFoundError("Organization not found")
        return organization

    async def _require_manageable_request(
        self,
        actor_user_id: UUID,
        verification_request_public_id: UUID,
    ) -> VerificationRequest:
        request = await self._get_required_request(verification_request_public_id)
        membership = await self._get_membership_for_request(request, actor_user_id)
        if membership is None:
            if request.subject_user_id == actor_user_id:
                raise ForbiddenError("The request subject cannot perform this action")
            raise NotFoundError("Verification request not found")
        return request

    async def _require_subject_request(
        self,
        actor_user_id: UUID,
        actor_email: str,
        verification_request_public_id: UUID,
    ) -> VerificationRequest:
        request = await self._get_required_request(verification_request_public_id)
        if self._is_subject_actor(request, actor_user_id, actor_email):
            return request
        membership = await self._get_membership_for_request(request, actor_user_id)
        if membership is not None:
            raise ForbiddenError("Only the request subject can access this route")
        raise NotFoundError("Verification request not found")

    async def _require_editable_subject_request(
        self,
        actor_user_id: UUID,
        actor_email: str,
        verification_request_public_id: UUID,
    ) -> VerificationRequest:
        request = await self._require_subject_request(actor_user_id, actor_email, verification_request_public_id)
        if request.status not in {
            VerificationRequestStatus.ACCEPTED,
            VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION,
            VerificationRequestStatus.AWAITING_SUBJECT_CORRECTIONS,
        }:
            raise ConflictError("Verification request is not editable by the subject in its current status")
        return request

    async def _get_accessible_request(
        self,
        *,
        actor_user_id: UUID,
        actor_email: str,
        verification_request_public_id: UUID,
    ) -> VerificationRequest:
        request = await self._get_required_request(verification_request_public_id)
        membership = await self._get_membership_for_request(request, actor_user_id)
        if membership is not None or self._is_subject_actor(request, actor_user_id, actor_email):
            return request
        raise NotFoundError("Verification request not found")

    async def _get_required_request(self, verification_request_public_id: UUID) -> VerificationRequest:
        request = await self._requests.get_by_public_id(verification_request_public_id)
        if request is None:
            raise NotFoundError("Verification request not found")
        return request

    async def _get_membership_for_request(self, request: VerificationRequest, actor_user_id: UUID):
        if request.organization_id is None:
            return None
        return await self._organizations.get_membership(request.organization_id, actor_user_id)

    def _is_subject_actor(
        self,
        request: VerificationRequest,
        actor_user_id: UUID,
        actor_email: str,
    ) -> bool:
        if request.subject_user_id is not None and request.subject_user_id == actor_user_id:
            return True
        if actor_email and self._normalize_email(actor_email) == request.subject_email:
            return True
        return False

    def _to_response(self, request: VerificationRequest) -> VerificationRequestResponse:
        return VerificationRequestResponse(
            public_id=request.public_id,
            employment_id=request.employment_id,
            origin_type=request.origin_type,
            organization_public_id=request.organization.public_id if request.organization is not None else None,
            trust_invitation_public_id=request.trust_invitation.public_id if request.trust_invitation is not None else None,
            subject_name=request.subject_name,
            subject_email=request.subject_email,
            target_organization_name=request.target_organization_name,
            target_organization_email=request.target_organization_email,
            request_type=request.request_type,
            status=request.status,
            due_date=request.due_date,
            trust_context=request.trust_context,
            created_at=request.created_at,
            updated_at=request.updated_at,
        )

    def _to_evidence_response(self, evidence: VerificationRequestEvidence) -> VerificationRequestEvidenceResponse:
        return VerificationRequestEvidenceResponse(
            public_id=evidence.public_id,
            evidence_type=evidence.evidence_type,
            field_key=evidence.field_key,
            document_id=evidence.document_id,
            value=evidence.value,
            status=evidence.status,
            created_at=evidence.created_at,
            updated_at=evidence.updated_at,
        )

    def _to_correction_response(self, correction) -> VerificationRequestCorrectionResponse:  # noqa: ANN001
        return VerificationRequestCorrectionResponse(
            public_id=correction.public_id,
            evidence_public_id=correction.evidence_item.public_id if correction.evidence_item is not None else None,
            field_key=correction.field_key,
            request_text=correction.request_text,
            guidance=correction.guidance,
            status=correction.status,
            created_at=correction.created_at,
            updated_at=correction.updated_at,
        )

    def _filter_request_responses(
        self,
        responses: list[VerificationRequestResponse],
        params: ListQueryParams,
    ) -> list[VerificationRequestResponse] | Page[VerificationRequestResponse]:
        return filter_sort_paginate(
            responses,
            params=params,
            search_fields=(
                "subject_name",
                "subject_email",
                "request_type",
                "status",
                "target_organization_name",
                "target_organization_email",
            ),
            allowed_sort_fields=(
                "created_at",
                "updated_at",
                "subject_name",
                "subject_email",
                "request_type",
                "status",
            ),
            default_sort_by="created_at",
        )

    def _merge_note_metadata(self, payload: VerificationRequestActionPayload) -> dict[str, object]:
        metadata: dict[str, object] = dict(payload.metadata)
        if payload.note:
            metadata["note"] = payload.note
        return metadata

    def _normalize_email(self, email: str) -> str:
        return email.strip().lower()

    def _organization_name(self, request: VerificationRequest) -> str:
        if request.organization is not None:
            return request.organization.name
        if request.target_organization_name:
            return request.target_organization_name
        return "the requested organization"

    def _subject_name(self, subject: User) -> str:
        if subject.full_name:
            return subject.full_name
        local_part = subject.email.split("@", 1)[0]
        return local_part.replace(".", " ").replace("_", " ").strip() or subject.email
