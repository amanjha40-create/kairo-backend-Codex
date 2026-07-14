"""Employer confirmation path — magic-link email and public verifier responses."""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import hash_refresh_token
from app.config import Settings, get_settings
from app.employment.enums import (
    EmployerVerificationDecision,
    VerificationAuditAction,
    VerificationMethod,
    VerificationStatus,
)
from app.employment.verification.state_machine import VerificationStatusManager
from app.exceptions import (
    ActiveVerificationPipelineConflictError,
    EmploymentCaseNotFoundError,
    EmploymentWorkflowError,
    ExpiredLinkError,
    NotFoundError,
    ConflictError,
    ValidationAppError,
)
from app.integrations.email.employer_verification_pages import render_result_page, render_review_page
from app.repositories.employment_document import EmploymentDocumentRepository
from app.infrastructure.s3.presign import generate_presigned_get_url
from app.integrations.email.sender import get_email_sender
from app.models.employer_verification_request import EmployerVerificationRequest
from app.models.employment_document import EmploymentDocument
from app.repositories.employer_verification import EmployerVerificationRepository
from app.repositories.employment import EmploymentRepository
from app.repositories.verification_audit import VerificationAuditRepository
from app.repositories.verification_request import VerificationRequestRepository
from app.services.verification_request_workflow_service import VerificationRequestWorkflowService
from app.services.notification_service import NotificationService
from app.notifications.contracts import NotificationRequest
from app.verification_requests.enums import VerificationRequestEventSource, VerificationRequestStatus
from app.schemas.employer_verification import (
    EmployerVerificationRequestBody,
    EmployerVerificationRequestResponse,
    EmployerVerificationStatusResponse,
    AdminEmployerVerificationResponse,
    AdminEmployerVerificationSummary,
    EmployerDecisionBody,
    EmployerPortalActionResponse,
    EmployerPortalCandidate,
    EmployerPortalContact,
    EmployerPortalEmployment,
    EmployerPortalEvidence,
    EmployerPortalTimelineEvent,
    EmployerPortalWorkspace,
    EmployerVerifyBody,
)
logger = logging.getLogger(__name__)

_PIPELINE_BLOCKING_OTHERS: tuple[str, ...] = (
    VerificationStatus.SUBMITTED.value,
    VerificationStatus.UNDER_REVIEW.value,
)


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    if len(local) <= 1:
        masked_local = "*"
    elif len(local) == 2:
        masked_local = f"{local[0]}*"
    else:
        masked_local = f"{local[0]}***{local[-1]}"
    return f"{masked_local}@{domain}"


def _normalize_verifier_email(email: str) -> str:
    return email.strip().lower()


class EmployerVerificationService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._employment = EmploymentRepository(session)
        self._requests = EmployerVerificationRepository(session)
        self._audit = VerificationAuditRepository(session)
        self._docs = EmploymentDocumentRepository(session)
        self._verification_requests = VerificationRequestRepository(session)
        self._workflow = VerificationRequestWorkflowService(self._verification_requests)
        self._email = get_email_sender(self._settings)

    def _review_link(self, token: str) -> str:
        base = (self._settings.employer_portal_base_url or self._settings.app_public_base_url).rstrip("/")
        return f"{base}/employer-verification/{token}"

    def _public_link(self, token: str, action: str) -> str:
        base = self._settings.app_public_base_url.rstrip("/")
        prefix = self._settings.api_v1_prefix.rstrip("/")
        return f"{base}{prefix}/public/employer-verification/{token}/{action}"

    async def _emit_audit(
        self,
        *,
        employment_id: UUID,
        actor_user_id: UUID | None,
        action: VerificationAuditAction,
        previous_status: str | None,
        new_status: str | None,
        metadata_payload: dict | None = None,
    ) -> None:
        await self._audit.append(
            employment_id=employment_id,
            actor_user_id=actor_user_id,
            action=action.value,
            previous_status=previous_status,
            new_status=new_status,
            metadata_payload=metadata_payload,
        )

    async def request_verification(
        self,
        owner_user_id: UUID,
        employment_id: UUID,
        payload: EmployerVerificationRequestBody,
        *,
        verification_request_id: UUID | None = None,
    ) -> EmployerVerificationRequestResponse:
        row = await self._employment.get_owned_active(employment_id, owner_user_id)
        if row is None:
            raise EmploymentCaseNotFoundError()
        if row.verification_status != VerificationStatus.DRAFT.value:
            raise EmploymentWorkflowError(
                "Employer verification can only be requested for draft cases",
            )

        verifier_email = _normalize_verifier_email(str(payload.verifier_email))
        now = datetime.now(tz=UTC)
        ttl = timedelta(hours=self._settings.employer_verification_token_ttl_hours)
        raw_token = secrets.token_urlsafe(32)
        token_hash = hash_refresh_token(raw_token)

        row.verification_method = VerificationMethod.EMPLOYER_CONFIRMATION.value

        existing = await self._requests.get_by_employment_id(employment_id)
        if existing is None:
            req = EmployerVerificationRequest(
                employment_id=employment_id,
                verification_request_id=verification_request_id,
                contact_name=payload.contact_name,
                verifier_email=verifier_email,
                relationship_to_subject=payload.relationship,
                token_hash=token_hash,
                expires_at=now + ttl,
                sent_at=now,
                responded_at=None,
                response=EmployerVerificationDecision.PENDING.value,
            )
            await self._requests.create(req)
        else:
            existing.contact_name = payload.contact_name
            existing.verification_request_id = verification_request_id
            existing.verifier_email = verifier_email
            existing.relationship_to_subject = payload.relationship
            existing.token_hash = token_hash
            existing.expires_at = now + ttl
            existing.sent_at = now
            existing.responded_at = None
            existing.viewed_at = None
            existing.revoked_at = None
            existing.revoked_by_user_id = None
            existing.response_metadata = {}
            existing.response = EmployerVerificationDecision.PENDING.value
            await self._requests.update(existing)

        await self._emit_audit(
            employment_id=employment_id,
            actor_user_id=owner_user_id,
            action=VerificationAuditAction.EMPLOYER_VERIFICATION_REQUESTED,
            previous_status=row.verification_status,
            new_status=row.verification_status,
            metadata_payload={
                "verifier_email_domain": verifier_email.split("@")[-1],
                "relationship": payload.relationship,
            },
        )

        review_url = self._review_link(raw_token)
        await self._email.send_employer_verification(
            to_email=verifier_email,
            contact_name=payload.contact_name,
            subject_full_name=row.subject_full_name,
            employer_name=row.employer_legal_name,
            job_title=row.job_title,
            relationship=payload.relationship,
            review_url=review_url,
            ttl_hours=self._settings.employer_verification_token_ttl_hours,
        )

        await self._session.commit()

        expires_at = now + ttl
        logger.info(
            "employer_verification.requested",
            extra={
                "employment_id": str(employment_id),
                "owner_user_id": str(owner_user_id),
                "verifier_email_domain": verifier_email.split("@")[-1],
            },
        )
        return EmployerVerificationRequestResponse(
            employment_id=employment_id,
            verifier_email_masked=mask_email(verifier_email),
            expires_at=expires_at,
        )

    async def initiate_admin_outreach(
        self,
        *,
        actor_user_id: UUID,
        verification_request,
        payload: EmployerVerificationRequestBody,
    ) -> EmployerVerificationRequestResponse:
        if verification_request.employment_id is None:
            raise EmploymentWorkflowError("Verification request is not linked to an employment")
        if verification_request.approved_for_organization_verification_at is None or verification_request.status not in {
            VerificationRequestStatus.APPROVED_FOR_ORGANIZATION_VERIFICATION,
            VerificationRequestStatus.PENDING_ORGANIZATION_RESOLUTION,
        }:
            raise EmploymentWorkflowError("Employer outreach requires Admin approval")
        response = await self.request_verification(
            verification_request.subject_user_id,
            verification_request.employment_id,
            payload,
            verification_request_id=verification_request.id,
        )
        await self._workflow.record_action(
            verification_request,
            actor_user_id=actor_user_id,
            event_type="hr_invitation_sent",
            event_source=VerificationRequestEventSource.ADMIN,
            metadata={"verifier_email_masked": response.verifier_email_masked},
        )
        await self._session.commit()
        return response

    async def get_admin_summary(self, public_id: UUID) -> AdminEmployerVerificationResponse:
        request = await self._requests.get_by_public_id(public_id)
        if request is None:
            raise NotFoundError("Employer verification not found")
        return AdminEmployerVerificationResponse(
            employer_verification=AdminEmployerVerificationSummary(
                public_id=request.public_id,
                status=EmployerVerificationDecision(request.response),
                masked_recipient=mask_email(request.verifier_email),
                delivery_status="accepted" if request.sent_at is not None else "queued",
                created_at=request.created_at,
                updated_at=request.updated_at,
            )
        )

    async def _load_by_token(self, raw_token: str) -> EmployerVerificationRequest:
        if not raw_token or len(raw_token) < 16:
            raise NotFoundError("This verification link is invalid or has expired")
        token_hash = hash_refresh_token(raw_token)
        req = await self._requests.get_by_token_hash(token_hash)
        if req is None:
            raise NotFoundError("This verification link is invalid or has expired")
        return req

    async def _assert_no_other_pipeline_case(self, employment) -> None:
        conflicts = await self._employment.count_owner_pipeline_excluding(
            employment.created_by_user_id,
            exclude_employment_id=employment.id,
            pipeline_statuses=_PIPELINE_BLOCKING_OTHERS,
        )
        if conflicts > 0:
            raise ActiveVerificationPipelineConflictError()

    async def _record_canonical_hr_result(
        self,
        request_row: EmployerVerificationRequest,
        decision: EmployerVerificationDecision,
    ) -> None:
        if request_row.verification_request_id is None:
            return
        request = await self._verification_requests.get_by_id(request_row.verification_request_id)
        if request is None:
            return
        if decision == EmployerVerificationDecision.CONFIRMED:
            if request.status == VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE:
                await self._workflow.transition(
                    request,
                    target_status=VerificationRequestStatus.IN_PROGRESS,
                    actor_user_id=None,
                    event_type="hr_verified",
                    event_source=VerificationRequestEventSource.ORGANIZATION,
                    metadata={},
                )
            if request.status == VerificationRequestStatus.IN_PROGRESS:
                await self._workflow.transition(
                    request,
                    target_status=VerificationRequestStatus.VERIFIED,
                    actor_user_id=None,
                    event_type="passport_updated",
                    event_source=VerificationRequestEventSource.SYSTEM,
                    metadata={"reason": "employment_verified"},
                )
        elif decision == EmployerVerificationDecision.DECLINED and request.status == VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE:
            await self._workflow.transition(
                request,
                target_status=VerificationRequestStatus.REJECTED,
                actor_user_id=None,
                event_type="hr_verified",
                event_source=VerificationRequestEventSource.ORGANIZATION,
                metadata={"decision": decision.value},
            )

    async def get_portal_workspace(self, raw_token: str) -> EmployerPortalWorkspace:
        req = await self._load_portal_token(raw_token)
        employment = req.employment
        request = None
        timeline = []
        if req.verification_request_id is not None:
            request = await self._verification_requests.get_by_id(req.verification_request_id)
            if request is not None:
                timeline = await self._verification_requests.list_timeline(request.id)

        if req.viewed_at is None:
            req.viewed_at = datetime.now(tz=UTC)
            if request is not None:
                await self._workflow.record_action(
                    request,
                    actor_user_id=None,
                    event_type="hr_link_opened",
                    event_source=VerificationRequestEventSource.ORGANIZATION,
                    metadata={},
                )
            await self._session.commit()

        documents = await self._docs.list_all_active_for_employment(employment.id)
        return EmployerPortalWorkspace(
            employer_verification_public_id=req.public_id,
            state="pending" if req.response == EmployerVerificationDecision.PENDING.value else "completed",
            decision=None if req.response == EmployerVerificationDecision.PENDING.value else EmployerVerificationDecision(req.response),
            expires_at=req.expires_at,
            candidate=EmployerPortalCandidate(full_name=employment.subject_full_name),
            employment=EmployerPortalEmployment(
                employer_name=employment.employer_trade_name or employment.employer_legal_name,
                job_title=employment.job_title,
                employment_type=employment.employment_type,
                start_date=employment.start_date.isoformat(),
                end_date=employment.end_date.isoformat() if employment.end_date else None,
                country=employment.work_location_country,
                region=employment.work_location_region,
            ),
            evidence_summary=[
                EmployerPortalEvidence(
                    document_type=document.document_type,
                    original_filename=document.original_filename,
                    mime_type=document.content_type,
                    file_size=document.byte_size,
                    status=document.verification_status,
                )
                for document in documents
            ],
            verification_request_public_id=request.public_id if request else None,
            verification_request_status=request.status.value if request and hasattr(request.status, "value") else request.status if request else None,
            employer_contact=EmployerPortalContact(
                contact_name=req.contact_name,
                relationship=req.relationship_to_subject,
                email_masked=mask_email(req.verifier_email),
            ),
            timeline=[
                EmployerPortalTimelineEvent(
                    event_type=event.event_type,
                    previous_status=event.previous_status,
                    new_status=event.new_status,
                    created_at=event.created_at,
                )
                for event in timeline
                if event.event_type != "internal_note_added"
            ],
        )

    async def verify_from_portal(
        self,
        raw_token: str,
        payload: EmployerVerifyBody,
    ) -> EmployerPortalActionResponse:
        if not (payload.employment_existed and payload.dates_correct and payload.role_correct):
            raise ValidationAppError(
                "Use reject or request clarification when employment details cannot all be confirmed"
            )
        return await self._respond_portal(
            raw_token,
            EmployerVerificationDecision.CONFIRMED,
            remarks=payload.comments,
            metadata={
                "employment_existed": payload.employment_existed,
                "dates_correct": payload.dates_correct,
                "role_correct": payload.role_correct,
            },
        )

    async def reject_from_portal(
        self,
        raw_token: str,
        payload: EmployerDecisionBody,
    ) -> EmployerPortalActionResponse:
        return await self._respond_portal(
            raw_token,
            EmployerVerificationDecision.DECLINED,
            remarks=payload.comments,
            metadata={"reason": payload.reason},
        )

    async def request_clarification_from_portal(
        self,
        raw_token: str,
        payload: EmployerDecisionBody,
    ) -> EmployerPortalActionResponse:
        return await self._respond_portal(
            raw_token,
            EmployerVerificationDecision.ON_HOLD,
            remarks=payload.comments,
            metadata={"reason": payload.reason},
        )

    async def revoke(self, public_id: UUID, actor_user_id: UUID) -> AdminEmployerVerificationResponse:
        req = await self._requests.get_by_public_id(public_id)
        if req is None:
            raise NotFoundError("Employer verification not found")
        if req.responded_at is not None:
            raise ConflictError("Completed employer verification links cannot be revoked")
        if req.revoked_at is None:
            req.revoked_at = datetime.now(tz=UTC)
            req.revoked_by_user_id = actor_user_id
            await self._session.commit()
        return await self.get_admin_summary(public_id)

    async def _load_portal_token(self, raw_token: str) -> EmployerVerificationRequest:
        req = await self._load_by_token(raw_token)
        if req.revoked_at is not None:
            raise NotFoundError("This verification link is invalid")
        if datetime.now(tz=UTC) > req.expires_at:
            raise ExpiredLinkError("This verification link has expired")
        return req

    async def _respond_portal(
        self,
        raw_token: str,
        decision: EmployerVerificationDecision,
        *,
        remarks: str | None,
        metadata: dict,
    ) -> EmployerPortalActionResponse:
        req = await self._load_portal_token(raw_token)
        employment = req.employment
        request = (
            await self._verification_requests.get_by_id(req.verification_request_id)
            if req.verification_request_id is not None
            else None
        )
        if req.response != EmployerVerificationDecision.PENDING.value:
            if req.response != decision.value:
                raise ConflictError("This verification link has already been used")
            return self._portal_action_response(req, employment, request, idempotent=True)
        if request is None or request.status != VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE:
            raise ConflictError("This verification request is not awaiting an employer response")

        now = datetime.now(tz=UTC)
        req.response = decision.value
        req.responded_at = now
        req.remarks = remarks
        req.response_metadata = metadata

        if decision == EmployerVerificationDecision.CONFIRMED:
            employment.verification_status = VerificationStatus.APPROVED.value
            employment.reviewed_at = now
            await self._session.execute(
                sa_update(EmploymentDocument)
                .where(EmploymentDocument.employment_id == employment.id)
                .values(verification_status="approved", verified_at=now)
            )
            await self._workflow.transition(
                request,
                target_status=VerificationRequestStatus.IN_PROGRESS,
                actor_user_id=None,
                event_type="hr_verified",
                event_source=VerificationRequestEventSource.ORGANIZATION,
                metadata=metadata,
            )
            await self._workflow.transition(
                request,
                target_status=VerificationRequestStatus.VERIFIED,
                actor_user_id=None,
                event_type="passport_updated",
                event_source=VerificationRequestEventSource.SYSTEM,
                metadata={"reason": "employment_verified"},
            )
            await self._notify_verification_completed(request)
        elif decision == EmployerVerificationDecision.DECLINED:
            employment.verification_status = VerificationStatus.REJECTED.value
            employment.reviewed_at = now
            await self._workflow.transition(
                request,
                target_status=VerificationRequestStatus.REJECTED,
                actor_user_id=None,
                event_type="hr_rejected",
                event_source=VerificationRequestEventSource.ORGANIZATION,
                metadata=metadata,
            )
        else:
            await self._workflow.transition(
                request,
                target_status=VerificationRequestStatus.IN_PROGRESS,
                actor_user_id=None,
                event_type="hr_requested_clarification",
                event_source=VerificationRequestEventSource.ORGANIZATION,
                metadata=metadata,
            )
            await self._workflow.transition(
                request,
                target_status=VerificationRequestStatus.AWAITING_INFORMATION,
                actor_user_id=None,
                event_type="awaiting_subject_information",
                event_source=VerificationRequestEventSource.SYSTEM,
                metadata={},
            )

        await self._emit_audit(
            employment_id=employment.id,
            actor_user_id=None,
            action={
                EmployerVerificationDecision.CONFIRMED: VerificationAuditAction.EMPLOYER_VERIFICATION_CONFIRMED,
                EmployerVerificationDecision.DECLINED: VerificationAuditAction.EMPLOYER_VERIFICATION_DECLINED,
                EmployerVerificationDecision.ON_HOLD: VerificationAuditAction.EMPLOYER_VERIFICATION_HELD,
            }[decision],
            previous_status=None,
            new_status=employment.verification_status,
            metadata_payload={"decision": decision.value},
        )
        await self._session.commit()
        return self._portal_action_response(req, employment, request)

    async def _notify_verification_completed(self, request) -> None:
        try:
            await NotificationService(self._session, self._settings).create_and_dispatch(
                NotificationRequest(
                    event_type="verification_completed",
                    recipient_user_id=request.subject_user_id,
                    recipient_email=request.subject_email,
                    payload={
                        "subject_name": request.subject_name,
                        "organization_name": request.organization.display_name if request.organization else "the organization",
                        "request_type": request.request_type.value,
                        "completed_at_iso": datetime.now(tz=UTC).isoformat(),
                    },
                    metadata={"verification_request_public_id": str(request.public_id)},
                )
            )
        except Exception:
            logger.warning("employer_verification_notification_failed", exc_info=True)

    @staticmethod
    def _portal_action_response(req, employment, request, *, idempotent: bool = False) -> EmployerPortalActionResponse:
        status_value = request.status.value if request and hasattr(request.status, "value") else request.status if request else None
        return EmployerPortalActionResponse(
            employer_verification_public_id=req.public_id,
            decision=EmployerVerificationDecision(req.response),
            verification_request_status=status_value,
            employment_verification_status=employment.verification_status,
            idempotent=idempotent,
        )

    async def respond_confirm(self, raw_token: str) -> str:
        return await self._respond(raw_token, decision=EmployerVerificationDecision.CONFIRMED)

    async def respond_decline(self, raw_token: str) -> str:
        return await self._respond(raw_token, decision=EmployerVerificationDecision.DECLINED)

    async def _respond(self, raw_token: str, *, decision: EmployerVerificationDecision) -> str:
        req = await self._load_by_token(raw_token)
        employment = req.employment
        now = datetime.now(tz=UTC)

        if req.response != EmployerVerificationDecision.PENDING.value:
            if req.response == decision.value:
                title = "Already recorded"
                message = (
                    "Your response was already saved. No further action is needed."
                )
                return render_result_page(title=title, message=message, success=True)
            title = "Link already used"
            message = "This verification link has already been used with a different response."
            return render_result_page(title=title, message=message, success=False)

        if now > req.expires_at:
            raise NotFoundError("This verification link has expired")

        prev_status = employment.verification_status

        if decision == EmployerVerificationDecision.CONFIRMED:
            if VerificationStatus.SUBMITTED.value not in VerificationStatusManager.allowed_targets(
                prev_status,
                role="applicant",
            ):
                title = "Cannot verify"
                message = "This employment case is no longer awaiting verification."
                return render_result_page(title=title, message=message, success=False)

            await self._assert_no_other_pipeline_case(employment)
            employment.verification_status = VerificationStatus.SUBMITTED.value
            employment.submitted_at = now
            employment.verification_method = VerificationMethod.EMPLOYER_CONFIRMATION.value

            req.response = EmployerVerificationDecision.CONFIRMED.value
            req.responded_at = now

            await self._session.execute(
                sa_update(EmploymentDocument)
                .where(EmploymentDocument.employment_id == employment.id)
                .values(verification_status="approved")
            )

            await self._emit_audit(
                employment_id=employment.id,
                actor_user_id=None,
                action=VerificationAuditAction.EMPLOYER_VERIFICATION_CONFIRMED,
                previous_status=prev_status,
                new_status=employment.verification_status,
                metadata_payload={"verifier_email_domain": req.verifier_email.split("@")[-1]},
            )
            await self._emit_audit(
                employment_id=employment.id,
                actor_user_id=None,
                action=VerificationAuditAction.EMPLOYMENT_SUBMITTED,
                previous_status=prev_status,
                new_status=employment.verification_status,
                metadata_payload={"via": "employer_confirmation"},
            )
            await self._record_canonical_hr_result(req, decision)

            await self._session.commit()
            logger.info(
                "employer_verification.confirmed",
                extra={"employment_id": str(employment.id)},
            )
            return render_result_page(
                title="Employment verified",
                message="Thank you. The employment record has been submitted for review.",
                success=True,
            )

        req.response = EmployerVerificationDecision.DECLINED.value
        req.responded_at = now

        await self._session.execute(
            sa_update(EmploymentDocument)
            .where(EmploymentDocument.employment_id == employment.id)
            .values(verification_status="rejected")
        )

        await self._emit_audit(
            employment_id=employment.id,
            actor_user_id=None,
            action=VerificationAuditAction.EMPLOYER_VERIFICATION_DECLINED,
            previous_status=prev_status,
            new_status=employment.verification_status,
            metadata_payload={"verifier_email_domain": req.verifier_email.split("@")[-1]},
        )
        await self._record_canonical_hr_result(req, decision)
        await self._session.commit()
        logger.info(
            "employer_verification.declined",
            extra={"employment_id": str(employment.id)},
        )
        return render_result_page(
            title="Response recorded",
            message="You indicated this person was not employed as described. The applicant has been notified.",
            success=True,
        )

    async def render_review_page(self, raw_token: str) -> str:
        req = await self._load_by_token(raw_token)
        employment = req.employment
        if req.verification_request_id is not None:
            request = await self._verification_requests.get_by_id(req.verification_request_id)
            if request is not None:
                await self._workflow.record_action(
                    request,
                    actor_user_id=None,
                    event_type="hr_link_opened",
                    event_source=VerificationRequestEventSource.ORGANIZATION,
                    metadata={},
                )
                await self._session.commit()

        docs = await self._docs.list_all_active_for_employment(employment.id)
        doc_list = []
        bucket = self._settings.s3_documents_bucket
        for d in docs:
            url = None
            if bucket and d.object_key:
                url = await generate_presigned_get_url(
                    bucket=bucket,
                    object_key=d.object_key,
                    ttl_seconds=3600,
                )
            doc_list.append({
                "original_filename": d.original_filename,
                "byte_size": d.byte_size,
                "download_url": url,
            })

        already_responded = req.response != EmployerVerificationDecision.PENDING.value
        return render_review_page(
            contact_name=req.contact_name,
            subject_full_name=employment.subject_full_name,
            subject_email=None,
            employer_name=employment.employer_legal_name,
            job_title=employment.job_title,
            start_date=str(employment.start_date),
            end_date=str(employment.end_date) if employment.end_date else None,
            relationship=req.relationship_to_subject,
            documents=doc_list,
            token=raw_token,
            base_url=self._settings.app_public_base_url,
            already_responded=already_responded,
            existing_response=req.response,
        )

    async def respond_with_action(self, raw_token: str, action: str, remarks: str | None) -> str:
        try:
            decision = EmployerVerificationDecision(action)
        except ValueError:
            from app.integrations.email.employer_verification_pages import render_result_page as _render
            return _render(
                title="Invalid action",
                message="The action you submitted is not recognised. Please use the form buttons.",
                success=False,
            )

        if decision == EmployerVerificationDecision.CONFIRMED:
            return await self._respond_with_remarks(raw_token, decision, remarks)
        if decision == EmployerVerificationDecision.DECLINED:
            return await self._respond_with_remarks(raw_token, decision, remarks)
        if decision == EmployerVerificationDecision.ON_HOLD:
            return await self._respond_with_remarks(raw_token, decision, remarks)

        from app.integrations.email.employer_verification_pages import render_result_page as _render
        return _render(title="Invalid action", message="Unknown response type.", success=False)

    async def _respond_with_remarks(
        self,
        raw_token: str,
        decision: EmployerVerificationDecision,
        remarks: str | None,
    ) -> str:
        req = await self._load_by_token(raw_token)
        employment = req.employment
        now = datetime.now(tz=UTC)

        if req.response != EmployerVerificationDecision.PENDING.value:
            label = {"confirmed": "Approved", "declined": "Declined", "on_hold": "On Hold"}.get(
                req.response, "responded"
            )
            return render_result_page(
                title="Already responded",
                message=f"Your response ({label}) has already been recorded. No further action needed.",
                success=True,
            )

        if now > req.expires_at:
            raise NotFoundError("This verification link has expired")

        prev_status = employment.verification_status
        req.response = decision.value
        req.responded_at = now
        req.remarks = remarks or None

        if decision == EmployerVerificationDecision.CONFIRMED:
            if VerificationStatus.SUBMITTED.value not in VerificationStatusManager.allowed_targets(
                prev_status, role="applicant"
            ):
                return render_result_page(
                    title="Cannot verify",
                    message="This employment case is no longer awaiting verification.",
                    success=False,
                )
            employment.verification_status = VerificationStatus.SUBMITTED.value
            employment.submitted_at = now
            employment.verification_method = VerificationMethod.EMPLOYER_CONFIRMATION.value

            await self._emit_audit(
                employment_id=employment.id,
                actor_user_id=None,
                action=VerificationAuditAction.EMPLOYER_VERIFICATION_CONFIRMED,
                previous_status=prev_status,
                new_status=employment.verification_status,
                metadata_payload={"verifier_email_domain": req.verifier_email.split("@")[-1]},
            )
            await self._emit_audit(
                employment_id=employment.id,
                actor_user_id=None,
                action=VerificationAuditAction.EMPLOYMENT_SUBMITTED,
                previous_status=prev_status,
                new_status=employment.verification_status,
                metadata_payload={"via": "employer_confirmation"},
            )
            await self._record_canonical_hr_result(req, decision)
            await self._session.commit()
            logger.info("employer_verification.confirmed", extra={"employment_id": str(employment.id)})
            return render_result_page(
                title="Employment verified",
                message="Thank you. The employment record has been submitted for review.",
                success=True,
            )

        if decision == EmployerVerificationDecision.ON_HOLD:
            audit_action = VerificationAuditAction.EMPLOYER_VERIFICATION_HELD
            result_title = "Placed on hold"
            result_message = "Your response has been recorded. The applicant will be notified."
        else:
            audit_action = VerificationAuditAction.EMPLOYER_VERIFICATION_DECLINED
            result_title = "Response recorded"
            result_message = "You indicated this person was not employed as described. The applicant has been notified."

        await self._emit_audit(
            employment_id=employment.id,
            actor_user_id=None,
            action=audit_action,
            previous_status=prev_status,
            new_status=employment.verification_status,
            metadata_payload={"verifier_email_domain": req.verifier_email.split("@")[-1]},
        )
        await self._record_canonical_hr_result(req, decision)
        await self._session.commit()
        logger.info(
            f"employer_verification.{decision.value}",
            extra={"employment_id": str(employment.id)},
        )
        return render_result_page(title=result_title, message=result_message, success=True)

    @staticmethod
    def status_from_request(req: EmployerVerificationRequest | None) -> EmployerVerificationStatusResponse | None:
        if req is None:
            return None
        return EmployerVerificationStatusResponse(
            contact_name=req.contact_name,
            verifier_email_masked=mask_email(req.verifier_email),
            relationship=req.relationship_to_subject,
            response=EmployerVerificationDecision(req.response),
            sent_at=req.sent_at,
            expires_at=req.expires_at,
            responded_at=req.responded_at,
        )
