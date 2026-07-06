"""Verification request engine use cases."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.trust_invitation import TrustInvitation
from app.models.verification_request import VerificationRequest
from app.repositories.organization import OrganizationRepository
from app.repositories.trust_invitation import TrustInvitationRepository
from app.repositories.user import UserRepository
from app.repositories.verification_request import VerificationRequestRepository
from app.schemas.verification_request import (
    VerificationRequestActionPayload,
    VerificationRequestCreateRequest,
    VerificationRequestResponse,
    VerificationRequestTimelineEventResponse,
    VerificationRequestTimelineResponse,
)
from app.services.verification_request_workflow_service import VerificationRequestWorkflowService
from app.verification_requests.enums import (
    VerificationRequestEventSource,
    VerificationRequestStatus,
)


class VerificationRequestService:
    """Canonical request management and authorization for verification workflows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._requests = VerificationRequestRepository(session)
        self._organizations = OrganizationRepository(session)
        self._users = UserRepository(session)
        self._trust_invitations = TrustInvitationRepository(session)
        self._workflow = VerificationRequestWorkflowService(self._requests)

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

        request = VerificationRequest(
            organization_id=organization.id,
            subject_user_id=subject_user_id,
            trust_invitation_id=trust_invitation.id if trust_invitation is not None else None,
            subject_name=subject_name,
            subject_email=subject_email,
            request_type=payload.request_type,
            status=VerificationRequestStatus.PENDING_SUBJECT_ACCEPTANCE,
            requested_by_user_id=actor_user_id,
            due_date=payload.due_date,
            trust_context=payload.trust_context,
        )
        await self._requests.create(request)
        await self._workflow.record_creation(
            request,
            actor_user_id=actor_user_id,
            event_source=VerificationRequestEventSource.ORGANIZATION,
            metadata={"request_type": payload.request_type.value},
        )
        await self._session.commit()
        await self._session.refresh(request)
        refreshed = await self._requests.get_by_public_id(request.public_id)
        if refreshed is None:
            raise NotFoundError("Verification request not found")
        return self._to_response(refreshed)

    async def list_for_organization(
        self,
        actor_user_id: UUID,
        organization_public_id: UUID,
    ) -> list[VerificationRequestResponse]:
        organization = await self._require_organization_member(actor_user_id, organization_public_id)
        items = await self._requests.list_for_organization(organization.id)
        return [self._to_response(item) for item in items]

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
            membership = await self._organizations.get_membership(request.organization_id, actor_user_id)
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
            allowed_current_statuses={VerificationRequestStatus.ACCEPTED},
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
        await self._transition_to_in_progress_if_needed(
            request,
            actor_user_id,
            payload.metadata,
            allowed_current_statuses={
                VerificationRequestStatus.ACCEPTED,
                VerificationRequestStatus.AWAITING_INFORMATION,
            },
        )
        await self._workflow.transition(
            request,
            target_status=VerificationRequestStatus.VERIFIED,
            actor_user_id=actor_user_id,
            event_type="verification_request_verified",
            event_source=VerificationRequestEventSource.ORGANIZATION,
            metadata=self._merge_note_metadata(payload),
        )
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
    ) -> VerificationRequestTimelineResponse:
        request = await self._get_accessible_request(
            actor_user_id=actor_user_id,
            actor_email=actor_email,
            verification_request_public_id=verification_request_public_id,
        )
        rows = await self._requests.list_timeline(request.id)
        return VerificationRequestTimelineResponse(
            verification_request_public_id=request.public_id,
            items=[
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
            ],
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
        membership = await self._organizations.get_membership(request.organization_id, actor_user_id)
        if membership is None:
            if request.subject_user_id == actor_user_id:
                raise ForbiddenError("The request subject cannot perform this action")
            raise NotFoundError("Verification request not found")
        return request

    async def _get_accessible_request(
        self,
        *,
        actor_user_id: UUID,
        actor_email: str,
        verification_request_public_id: UUID,
    ) -> VerificationRequest:
        request = await self._get_required_request(verification_request_public_id)
        membership = await self._organizations.get_membership(request.organization_id, actor_user_id)
        if membership is not None or self._is_subject_actor(request, actor_user_id, actor_email):
            return request
        raise NotFoundError("Verification request not found")

    async def _get_required_request(self, verification_request_public_id: UUID) -> VerificationRequest:
        request = await self._requests.get_by_public_id(verification_request_public_id)
        if request is None:
            raise NotFoundError("Verification request not found")
        return request

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
            organization_public_id=request.organization.public_id,
            trust_invitation_public_id=request.trust_invitation.public_id if request.trust_invitation is not None else None,
            subject_name=request.subject_name,
            subject_email=request.subject_email,
            request_type=request.request_type,
            status=request.status,
            due_date=request.due_date,
            trust_context=request.trust_context,
            created_at=request.created_at,
            updated_at=request.updated_at,
        )

    def _merge_note_metadata(self, payload: VerificationRequestActionPayload) -> dict[str, object]:
        metadata: dict[str, object] = dict(payload.metadata)
        if payload.note:
            metadata["note"] = payload.note
        return metadata

    def _normalize_email(self, email: str) -> str:
        return email.strip().lower()
