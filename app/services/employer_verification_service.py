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
    NotFoundError,
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
from app.schemas.employer_verification import (
    EmployerVerificationRequestBody,
    EmployerVerificationRequestResponse,
    EmployerVerificationStatusResponse,
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
        self._email = get_email_sender(self._settings)

    def _review_link(self, token: str) -> str:
        base = self._settings.app_public_base_url.rstrip("/")
        prefix = self._settings.api_v1_prefix.rstrip("/")
        return f"{base}{prefix}/public/employer-verification/{token}"

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
            existing.verifier_email = verifier_email
            existing.relationship_to_subject = payload.relationship
            existing.token_hash = token_hash
            existing.expires_at = now + ttl
            existing.sent_at = now
            existing.responded_at = None
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
