"""Admin reviewer workflows — operational queues and audited transitions."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import VERIFICATION_REVIEW_ROLES
from app.employment.constants import PENDING_UPLOAD_CHECKSUM_HEX
from app.employment.enums import (
    DocumentVerificationStatus,
    VerificationAuditAction,
    VerificationMethod,
    VerificationStatus,
)
from app.employment.verification.state_machine import VerificationStatusManager
from app.exceptions import EmploymentCaseNotFoundError, ValidationAppError
from app.repositories.admin import AdminRepository
from app.repositories.user import UserRepository
from app.schemas.admin_verification import VerificationAuditEntryPublic
from app.schemas.employment import (
    AdminVerificationTransitionRequest,
    EmploymentDetail,
    EmploymentDocumentResponse,
    EmploymentPublic,
)
from app.schemas.pagination import Page
from app.services.verification_queue_service import VerificationQueueService

logger = logging.getLogger(__name__)

_ASSIGNABLE_STATUSES: frozenset[str] = frozenset(
    {
        VerificationStatus.SUBMITTED.value,
        VerificationStatus.UNDER_REVIEW.value,
        VerificationStatus.ADDITIONAL_INFO_REQUESTED.value,
    }
)

_DOCUMENT_REVIEWABLE_EMPLOYMENT_STATUSES: frozenset[str] = frozenset(
    {
        VerificationStatus.SUBMITTED.value,
        VerificationStatus.UNDER_REVIEW.value,
        VerificationStatus.ADDITIONAL_INFO_REQUESTED.value,
    }
)

_REVIEWABLE_DOCUMENT_STATUSES: frozenset[str] = frozenset(
    {
        DocumentVerificationStatus.PENDING_REVIEW.value,
        DocumentVerificationStatus.REJECTED.value,
        DocumentVerificationStatus.APPROVED.value,
    }
)


class AdminReviewService:
    """Privileged transitions — must run behind RBAC dependencies."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._admin = AdminRepository(session)
        self._queues = VerificationQueueService(session)
        self._users = UserRepository(session)

    def _employment_detail(
        self,
        row,
        *,
        documents: list | None = None,
    ) -> EmploymentDetail:
        detail = EmploymentDetail.model_validate(row)
        if documents is not None:
            detail.documents = [EmploymentDocumentResponse.model_validate(d) for d in documents]
        elif getattr(row, "documents", None):
            detail.documents = [EmploymentDocumentResponse.model_validate(d) for d in row.documents]
        return detail

    async def _assert_all_documents_approved_for_case(self, employment_id: UUID) -> None:
        row = await self._admin.get_employment_detail(employment_id, load_documents=True)
        if row is None:
            raise EmploymentCaseNotFoundError()
        if row.verification_method != VerificationMethod.DOCUMENT.value:
            return

        uploaded = [
            d
            for d in (row.documents or [])
            if d.checksum_sha256 != PENDING_UPLOAD_CHECKSUM_HEX
        ]
        if not uploaded:
            raise ValidationAppError("Case has no completed document uploads to approve")

        pending = [d for d in uploaded if d.verification_status == DocumentVerificationStatus.PENDING_REVIEW.value]
        if pending:
            raise ValidationAppError(
                "All documents must be approved before approving the employment case",
            )
        rejected = [d for d in uploaded if d.verification_status == DocumentVerificationStatus.REJECTED.value]
        if rejected:
            raise ValidationAppError(
                "One or more documents were rejected — cannot approve the employment case",
            )
        not_approved = [
            d for d in uploaded if d.verification_status != DocumentVerificationStatus.APPROVED.value
        ]
        if not_approved:
            raise ValidationAppError("All documents must be approved before approving the employment case")

    async def list_queue(
        self,
        *,
        offset: int,
        limit: int,
        statuses: list[str] | None,
        employer_ilike: str | None,
        created_after: date | None,
        created_before: date | None,
    ) -> Page[EmploymentPublic]:
        return await self._queues.list_review_queue(
            offset=offset,
            limit=limit,
            statuses=statuses,
            employer_ilike=employer_ilike,
            created_after=created_after,
            created_before=created_before,
        )

    async def get_detail(self, employment_id: UUID) -> EmploymentDetail:
        row = await self._admin.get_employment_detail(employment_id, load_documents=True)
        if row is None:
            raise EmploymentCaseNotFoundError()
        return self._employment_detail(row)

    async def transition(
        self,
        actor_user_id: UUID,
        employment_id: UUID,
        payload: AdminVerificationTransitionRequest,
    ) -> EmploymentDetail:
        row = await self._admin.get_employment_detail(employment_id, load_documents=False)
        if row is None:
            raise EmploymentCaseNotFoundError()

        current = row.verification_status
        target = payload.new_status.value

        VerificationStatusManager.require_admin_transition(current, target)

        if target in (VerificationStatus.APPROVED.value, VerificationStatus.REJECTED.value):
            if not payload.summary or not str(payload.summary).strip():
                raise ValidationAppError("summary is required for approval or rejection decisions")

        if target == VerificationStatus.APPROVED.value:
            await self._assert_all_documents_approved_for_case(employment_id)

        if target == VerificationStatus.ADDITIONAL_INFO_REQUESTED.value:
            if not payload.pending_info_request or not payload.pending_info_request.strip():
                raise ValidationAppError("pending_info_request is required for this transition")

        prev = current
        row.verification_status = target

        if target in (VerificationStatus.APPROVED.value, VerificationStatus.REJECTED.value):
            row.reviewed_at = datetime.now(tz=UTC)
            row.reviewed_by_user_id = actor_user_id
            row.reviewer_summary = payload.summary
        elif target == VerificationStatus.ADDITIONAL_INFO_REQUESTED.value:
            row.pending_info_request = payload.pending_info_request
            row.reviewer_summary = payload.summary

        await self._admin.verification().append(
            employment_id=row.id,
            actor_user_id=actor_user_id,
            action=VerificationAuditAction.VERIFICATION_STATUS_CHANGED.value,
            previous_status=prev,
            new_status=target,
            metadata_payload={
                "summary": payload.summary,
                "pending_info_request": payload.pending_info_request,
            },
        )
        await self._session.commit()
        await self._session.refresh(row)
        logger.info(
            "admin.verification.transition",
            extra={
                "employment_id": str(employment_id),
                "actor_user_id": str(actor_user_id),
                "new_status": target,
            },
        )
        return self._employment_detail(row)

    async def approve_document(
        self,
        actor_user_id: UUID,
        employment_id: UUID,
        document_id: UUID,
        *,
        note: str | None = None,
    ) -> EmploymentDocumentResponse:
        doc = await self._review_document_transition(
            actor_user_id,
            employment_id,
            document_id,
            target_status=DocumentVerificationStatus.APPROVED,
            note=note,
            require_note=False,
        )
        return EmploymentDocumentResponse.model_validate(doc)

    async def reject_document(
        self,
        actor_user_id: UUID,
        employment_id: UUID,
        document_id: UUID,
        *,
        note: str,
    ) -> EmploymentDocumentResponse:
        doc = await self._review_document_transition(
            actor_user_id,
            employment_id,
            document_id,
            target_status=DocumentVerificationStatus.REJECTED,
            note=note,
            require_note=True,
        )
        return EmploymentDocumentResponse.model_validate(doc)

    async def _review_document_transition(
        self,
        actor_user_id: UUID,
        employment_id: UUID,
        document_id: UUID,
        *,
        target_status: DocumentVerificationStatus,
        note: str | None,
        require_note: bool,
    ):
        if require_note and (not note or not note.strip()):
            raise ValidationAppError("note is required when rejecting a document")

        row = await self._admin.get_employment_detail(employment_id, load_documents=False)
        if row is None:
            raise EmploymentCaseNotFoundError()
        if row.verification_method != VerificationMethod.DOCUMENT.value:
            raise ValidationAppError("Document review applies only to document verification cases")
        if row.verification_status not in _DOCUMENT_REVIEWABLE_EMPLOYMENT_STATUSES:
            raise ValidationAppError("Documents cannot be reviewed in the current case status")

        doc = await self._admin.documents().get_active_for_employment(employment_id, document_id)
        if doc is None:
            raise ValidationAppError("Document not found for this employment case")
        if doc.checksum_sha256 == PENDING_UPLOAD_CHECKSUM_HEX:
            raise ValidationAppError("Cannot review a document that has not finished uploading")
        if doc.verification_status not in _REVIEWABLE_DOCUMENT_STATUSES:
            raise ValidationAppError("Document cannot be reviewed in its current state")

        prev = doc.verification_status
        doc.verification_status = target_status.value
        doc.verified_at = datetime.now(tz=UTC)
        doc.verified_by_user_id = actor_user_id
        doc.reviewer_note = note.strip() if note else None

        action = (
            VerificationAuditAction.DOCUMENT_VERIFICATION_APPROVED
            if target_status == DocumentVerificationStatus.APPROVED
            else VerificationAuditAction.DOCUMENT_VERIFICATION_REJECTED
        )
        await self._admin.verification().append(
            employment_id=employment_id,
            actor_user_id=actor_user_id,
            action=action.value,
            previous_status=row.verification_status,
            new_status=row.verification_status,
            metadata_payload={
                "document_id": str(document_id),
                "document_verification_status": target_status.value,
                "previous_document_verification_status": prev,
                "note": doc.reviewer_note,
            },
        )
        await self._session.commit()
        await self._session.refresh(doc)
        logger.info(
            "admin.document.verification",
            extra={
                "employment_id": str(employment_id),
                "document_id": str(document_id),
                "actor_user_id": str(actor_user_id),
                "verification_status": target_status.value,
            },
        )
        return doc

    async def approve_verification(
        self,
        actor_user_id: UUID,
        employment_id: UUID,
        *,
        summary: str,
    ) -> EmploymentDetail:
        payload = AdminVerificationTransitionRequest(
            new_status=VerificationStatus.APPROVED,
            summary=summary,
        )
        return await self.transition(actor_user_id, employment_id, payload)

    async def reject_verification(
        self,
        actor_user_id: UUID,
        employment_id: UUID,
        *,
        summary: str,
    ) -> EmploymentDetail:
        payload = AdminVerificationTransitionRequest(
            new_status=VerificationStatus.REJECTED,
            summary=summary,
        )
        return await self.transition(actor_user_id, employment_id, payload)

    async def assign_review(
        self,
        actor_user_id: UUID,
        employment_id: UUID,
        *,
        assignee_user_id: UUID,
        start_review: bool = True,
    ) -> EmploymentDetail:
        row = await self._admin.get_employment_detail(employment_id, load_documents=False)
        if row is None:
            raise EmploymentCaseNotFoundError()

        if row.verification_status not in _ASSIGNABLE_STATUSES:
            raise ValidationAppError("Case cannot be assigned in the current status")

        assignee = await self._users.get_by_id(assignee_user_id)
        if assignee is None or not assignee.is_active:
            raise ValidationAppError("Assignee not found or inactive")
        if assignee.role not in VERIFICATION_REVIEW_ROLES:
            raise ValidationAppError("Assignee must be a verification reviewer")

        prev_status = row.verification_status
        prev_assignee = row.assigned_reviewer_user_id

        row.assigned_reviewer_user_id = assignee_user_id
        row.assigned_at = datetime.now(tz=UTC)

        started_review = False
        if start_review and prev_status == VerificationStatus.SUBMITTED.value:
            VerificationStatusManager.require_admin_transition(
                prev_status,
                VerificationStatus.UNDER_REVIEW.value,
            )
            row.verification_status = VerificationStatus.UNDER_REVIEW.value
            started_review = True

        new_status = row.verification_status

        await self._admin.verification().append(
            employment_id=row.id,
            actor_user_id=actor_user_id,
            action=VerificationAuditAction.REVIEW_ASSIGNED.value,
            previous_status=prev_status,
            new_status=new_status,
            metadata_payload={
                "assignee_user_id": str(assignee_user_id),
                "previous_assignee_user_id": str(prev_assignee) if prev_assignee else None,
                "started_review": started_review,
            },
        )

        await self._session.commit()
        await self._session.refresh(row)
        logger.info(
            "admin.verification.assign",
            extra={
                "employment_id": str(employment_id),
                "actor_user_id": str(actor_user_id),
                "assignee_user_id": str(assignee_user_id),
                "started_review": started_review,
            },
        )
        return self._employment_detail(row)

    async def add_remark(
        self,
        actor_user_id: UUID,
        employment_id: UUID,
        *,
        remark: str,
    ) -> EmploymentDetail:
        row = await self._admin.get_employment_detail(employment_id, load_documents=False)
        if row is None:
            raise EmploymentCaseNotFoundError()

        cur = row.verification_status
        await self._admin.verification().append(
            employment_id=row.id,
            actor_user_id=actor_user_id,
            action=VerificationAuditAction.REVIEWER_REMARK_ADDED.value,
            previous_status=cur,
            new_status=cur,
            metadata_payload={"remark": remark},
        )
        await self._session.commit()
        await self._session.refresh(row)
        logger.info(
            "admin.verification.remark",
            extra={"employment_id": str(employment_id), "actor_user_id": str(actor_user_id)},
        )
        return self._employment_detail(row)

    async def list_verification_history(
        self,
        employment_id: UUID,
        *,
        offset: int,
        limit: int,
        order: Literal["asc", "desc"] = "desc",
    ) -> Page[VerificationAuditEntryPublic]:
        """Paginated immutable audit stream — newest-first by default."""

        rows, total = await self._admin.verification().list_for_employment(
            employment_id,
            offset=offset,
            limit=limit,
            order=order,
        )
        return Page(
            items=[VerificationAuditEntryPublic.model_validate(r) for r in rows],
            total=total,
            offset=offset,
            limit=limit,
        )


AdminVerificationService = AdminReviewService
