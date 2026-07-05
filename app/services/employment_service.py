"""Employment verification cases — applicant-facing workflow and persistence orchestration."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.employment.constants import PENDING_UPLOAD_CHECKSUM_HEX
from app.employment.enums import EmploymentType, VerificationAuditAction, VerificationMethod, VerificationStatus
from app.employment.verification.state_machine import VerificationStatusManager
from app.employment.validation import validate_period_after_patch
from app.exceptions import (
    ActiveVerificationPipelineConflictError,
    EmploymentCaseNotFoundError,
    EmploymentWorkflowError,
)
from app.models.employment import Employment
from app.repositories.employment import EmploymentRepository
from app.repositories.employment_document import EmploymentDocumentRepository
from app.repositories.user import UserRepository
from app.repositories.verification_audit import VerificationAuditRepository
from app.schemas.employment import (
    EmploymentCancelResponse,
    EmploymentCreate,
    EmploymentDetail,
    EmploymentPublic,
    EmploymentSubmitResponse,
    EmploymentUpdate,
)
from app.schemas.pagination import Page
from app.services.employer_verification_service import EmployerVerificationService

logger = logging.getLogger(__name__)

_PIPELINE_BLOCKING_OTHERS: tuple[str, ...] = (
    VerificationStatus.SUBMITTED.value,
    VerificationStatus.UNDER_REVIEW.value,
)


class EmploymentService:
    """Owns applicant transitions — commits per use case."""

    def __init__(
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session
        self._employment = EmploymentRepository(session)
        self._documents = EmploymentDocumentRepository(session)
        self._audit = VerificationAuditRepository(session)
        self._users = UserRepository(session)

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

    async def create(self, owner_user_id: UUID, payload: EmploymentCreate) -> EmploymentPublic:
        row = Employment(
            created_by_user_id=owner_user_id,
            subject_full_name=payload.subject_full_name,
            subject_email=str(payload.subject_email) if payload.subject_email else None,
            employer_legal_name=payload.employer_legal_name,
            employer_trade_name=payload.employer_trade_name,
            job_title=payload.job_title,
            employment_type=payload.employment_type.value,
            start_date=payload.start_date,
            end_date=payload.end_date,
            work_location_country=payload.work_location_country,
            work_location_region=payload.work_location_region,
            verification_method=payload.verification_method.value,
            verification_status=VerificationStatus.DRAFT.value,
        )
        row = await self._employment.create(row)
        await self._emit_audit(
            employment_id=row.id,
            actor_user_id=owner_user_id,
            action=VerificationAuditAction.EMPLOYMENT_CREATED,
            previous_status=None,
            new_status=row.verification_status,
            metadata_payload={"employer_legal_name": row.employer_legal_name},
        )
        await self._users.mark_employment_onboarding_completed_if_needed(owner_user_id)
        await self._session.commit()
        logger.info(
            "employment.created",
            extra={"employment_id": str(row.id), "owner_user_id": str(owner_user_id)},
        )
        return EmploymentPublic.model_validate(row)

    async def update(self, owner_user_id: UUID, employment_id: UUID, payload: EmploymentUpdate) -> EmploymentPublic:
        row = await self._employment.get_owned_active(employment_id, owner_user_id)
        if row is None:
            raise EmploymentCaseNotFoundError()
        if row.verification_status not in (
            VerificationStatus.DRAFT.value,
            VerificationStatus.ADDITIONAL_INFO_REQUESTED.value,
        ):
            raise EmploymentWorkflowError("Employment cannot be edited in the current status")

        data = payload.model_dump(exclude_unset=True)
        for field, value in data.items():
            if field == "employment_type" and value is not None:
                value = value.value if isinstance(value, EmploymentType) else EmploymentType(str(value)).value
            if field == "subject_email" and value is not None:
                value = str(value)
            setattr(row, field, value)

        validate_period_after_patch(row)

        await self._emit_audit(
            employment_id=row.id,
            actor_user_id=owner_user_id,
            action=VerificationAuditAction.EMPLOYMENT_UPDATED,
            previous_status=None,
            new_status=row.verification_status,
            metadata_payload={"fields": list(data.keys())},
        )
        await self._session.commit()
        await self._session.refresh(row)
        logger.info(
            "employment.updated",
            extra={"employment_id": str(employment_id), "owner_user_id": str(owner_user_id)},
        )
        return EmploymentPublic.model_validate(row)

    async def delete_owned(self, owner_user_id: UUID, employment_id: UUID) -> None:
        """Soft-delete draft / additional-info cases and cascade to evidence rows."""

        row = await self._employment.get_owned_active(employment_id, owner_user_id)
        if row is None:
            raise EmploymentCaseNotFoundError()
        if row.verification_status not in (
            VerificationStatus.DRAFT.value,
            VerificationStatus.ADDITIONAL_INFO_REQUESTED.value,
        ):
            raise EmploymentWorkflowError(
                "Only draft or additional-information cases can be deleted by the applicant",
            )

        await self._documents.soft_delete_all_for_employment(employment_id)
        await self._employment.soft_delete(employment_id)
        await self._emit_audit(
            employment_id=employment_id,
            actor_user_id=owner_user_id,
            action=VerificationAuditAction.EMPLOYMENT_UPDATED,
            previous_status=row.verification_status,
            new_status=row.verification_status,
            metadata_payload={"soft_deleted": True},
        )
        await self._session.commit()
        logger.info(
            "employment.soft_deleted",
            extra={"employment_id": str(employment_id), "owner_user_id": str(owner_user_id)},
        )

    async def list_audit_events_owned(
        self,
        owner_user_id: UUID,
        employment_id: UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list, int]:
        """Audit trail for an employment owned by the user — shows who approved/reviewed."""

        # Verify ownership
        row = await self._employment.get_owned_active(employment_id, owner_user_id)
        if row is None:
            raise EmploymentCaseNotFoundError()

        return await self._audit.list_for_employment(
            employment_id,
            offset=offset,
            limit=limit,
            order="desc",
        )

    async def get_detail_owned(self, owner_user_id: UUID, employment_id: UUID) -> EmploymentDetail:
        row = await self._employment.get_owned_active_with_employer_request(employment_id, owner_user_id)
        if row is None:
            raise EmploymentCaseNotFoundError()
        detail = EmploymentDetail.model_validate(row)
        detail.employer_verification = EmployerVerificationService.status_from_request(
            row.employer_verification_request,
        )
        return detail

    async def list_owned(
        self,
        owner_user_id: UUID,
        *,
        offset: int,
        limit: int,
        statuses: list[str] | None,
        employer_ilike: str | None,
    ) -> Page[EmploymentPublic]:
        items, total = await self._employment.list_for_owner(
            owner_user_id,
            offset=offset,
            limit=limit,
            statuses=statuses,
            employer_ilike=employer_ilike,
        )
        return Page(
            items=[EmploymentPublic.model_validate(r) for r in items],
            total=total,
            offset=offset,
            limit=limit,
        )

    async def _assert_no_other_active_pipeline_case(self, owner_user_id: UUID, employment_id: UUID) -> None:
        conflicts = await self._employment.count_owner_pipeline_excluding(
            owner_user_id,
            exclude_employment_id=employment_id,
            pipeline_statuses=_PIPELINE_BLOCKING_OTHERS,
        )
        if conflicts > 0:
            logger.warning(
                "employment.submit.pipeline_conflict",
                extra={"owner_user_id": str(owner_user_id), "employment_id": str(employment_id)},
            )
            raise ActiveVerificationPipelineConflictError()

    async def submit(self, owner_user_id: UUID, employment_id: UUID) -> EmploymentSubmitResponse:
        # Lock the row for the duration of this transaction so that concurrent
        # submit calls are serialised and cannot both pass the pipeline-conflict
        # check simultaneously.
        row = await self._employment.get_owned_active_for_update(employment_id, owner_user_id)
        if row is None:
            raise EmploymentCaseNotFoundError()

        prev = row.verification_status
        if VerificationStatus.SUBMITTED.value not in VerificationStatusManager.allowed_targets(
            prev,
            role="applicant",
        ):
            raise EmploymentWorkflowError("Case cannot be submitted in the current status")

        if prev == VerificationStatus.DRAFT.value:
            if row.verification_method == VerificationMethod.EMPLOYER_CONFIRMATION.value:
                raise EmploymentWorkflowError(
                    "Employer confirmation cases are submitted when the verifier responds. "
                    "Send an employer verification request from the app.",
                )
            await self._assert_no_other_active_pipeline_case(owner_user_id, employment_id)
            doc_count = await self._documents.count_completed_for_employment(
                employment_id,
                pending_checksum_hex=PENDING_UPLOAD_CHECKSUM_HEX,
            )
            if doc_count < 1:
                raise EmploymentWorkflowError("Submit requires at least one completed document upload")
            row.verification_status = VerificationStatus.SUBMITTED.value
            row.submitted_at = datetime.now(tz=UTC)
        elif prev == VerificationStatus.ADDITIONAL_INFO_REQUESTED.value:
            await self._assert_no_other_active_pipeline_case(owner_user_id, employment_id)
            row.verification_status = VerificationStatus.SUBMITTED.value
            row.submitted_at = datetime.now(tz=UTC)
            row.pending_info_request = None

        await self._emit_audit(
            employment_id=row.id,
            actor_user_id=owner_user_id,
            action=VerificationAuditAction.EMPLOYMENT_SUBMITTED,
            previous_status=prev,
            new_status=row.verification_status,
        )
        await self._session.commit()
        await self._session.refresh(row)
        logger.info(
            "employment.submitted",
            extra={"employment_id": str(employment_id), "owner_user_id": str(owner_user_id)},
        )
        return EmploymentSubmitResponse(employment=EmploymentPublic.model_validate(row))

    async def cancel(self, owner_user_id: UUID, employment_id: UUID) -> EmploymentCancelResponse:
        row = await self._employment.get_owned_active(employment_id, owner_user_id)
        if row is None:
            raise EmploymentCaseNotFoundError()
        if VerificationStatus.CANCELLED.value not in VerificationStatusManager.allowed_targets(
            row.verification_status,
            role="applicant",
        ):
            raise EmploymentWorkflowError("Only draft or submitted cases can be cancelled by the applicant")

        prev = row.verification_status
        row.verification_status = VerificationStatus.CANCELLED.value
        await self._emit_audit(
            employment_id=row.id,
            actor_user_id=owner_user_id,
            action=VerificationAuditAction.EMPLOYMENT_CANCELLED,
            previous_status=prev,
            new_status=row.verification_status,
        )
        await self._session.commit()
        await self._session.refresh(row)
        logger.info(
            "employment.cancelled",
            extra={"employment_id": str(employment_id), "owner_user_id": str(owner_user_id)},
        )
        return EmploymentCancelResponse(employment=EmploymentPublic.model_validate(row))
