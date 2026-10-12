"""Shared inspection predicate and lock order for review/replacement/finalization."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin_review.enums import VerificationRequestEvidenceStatus
from app.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models.education import Education
from app.models.education_document import EducationDocument
from app.models.employment import Employment
from app.models.employment_document import EmploymentDocument
from app.models.user_document import UserDocument
from app.models.verification_request import VerificationRequest
from app.models.verification_request_evidence import VerificationRequestEvidence
from app.repositories.verification_request import VerificationRequestRepository
from app.repositories.verification_request_evidence import VerificationRequestEvidenceRepository
from app.services.verification_request_workflow_service import VerificationRequestWorkflowService
from app.verification_requests.enums import VerificationRequestEventSource


async def lock_evidence_case(session: AsyncSession, public_id: UUID) -> VerificationRequest:
    repo = VerificationRequestRepository(session)
    request = await repo.get_by_public_id(public_id)
    if request is None:
        raise NotFoundError("Verification request not found")
    await lock_review_subject(session, request.subject_user_id)
    # Existing Candidate uploads lock the canonical claim first. Keep that order.
    for model, claim_id in ((Employment, request.employment_id), (Education, request.education_id)):
        if claim_id is not None:
            await session.execute(select(model.id).where(model.id == claim_id).with_for_update())
    locked = await repo.get_by_public_id_for_update(public_id)
    if locked is None:
        raise NotFoundError("Verification request not found")
    return locked


async def lock_review_subject(session: AsyncSession, user_id: UUID | None) -> None:
    # Shared documents can belong to multiple cases. Serialize content completion
    # before claim/case locks, including a concurrent first attachment to a case.
    if user_id is not None:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"evidence-review:{user_id}"},
        )


async def applicable_evidence(
    session: AsyncSession, request: VerificationRequest
) -> list[VerificationRequestEvidence]:
    items = await VerificationRequestEvidenceRepository(session).list_for_request(request.id)
    result = []
    for item in items:
        if item.status == VerificationRequestEvidenceStatus.SUPERSEDED:
            continue
        applicable = True
        for model, document_id, parent_field, parent_id in (
            (
                EmploymentDocument,
                item.employment_document_id,
                "employment_id",
                request.employment_id,
            ),
            (EducationDocument, item.education_document_id, "education_id", request.education_id),
            (UserDocument, item.document_id, "user_id", request.subject_user_id),
        ):
            if document_id is None:
                continue
            document = await session.get(model, document_id, populate_existing=True)
            if (
                document is None
                or document.deleted_at is not None
                or getattr(document, "superseded_at", None) is not None
                or getattr(document, parent_field) != parent_id
            ):
                applicable = False
                break
        if applicable:
            result.append(item)
    return result


async def require_evidence_review_complete(
    session: AsyncSession, request: VerificationRequest
) -> None:
    items = await applicable_evidence(session, request)
    reviewed = sum(item.reviewed_at is not None for item in items)
    if reviewed != len(items):
        raise ValidationAppError(
            f"Evidence review incomplete: {reviewed}/{len(items)} applicable items reviewed",
            code="evidence_review_incomplete",
        )


def content_identity(item: VerificationRequestEvidence) -> tuple:
    return (
        item.document_id,
        item.employment_document_id,
        item.education_document_id,
        item.evidence_type,
        item.field_key,
        item.value,
    )


async def invalidate_changed_review(session, request, item, before, actor_user_id) -> None:
    if before == content_identity(item) or item.reviewed_at is None:
        return
    await invalidate_review(session, request, item, actor_user_id)


async def invalidate_review(session, request, item, actor_user_id) -> None:
    if item.reviewed_at is None:
        return
    previous_at, previous_by = item.reviewed_at, item.reviewed_by_user_id
    item.reviewed_at = None
    item.reviewed_by_user_id = None
    await VerificationRequestWorkflowService(VerificationRequestRepository(session)).record_action(
        request,
        actor_user_id=actor_user_id,
        event_type="evidence_review_invalidated",
        event_source=VerificationRequestEventSource.CANDIDATE,
        metadata={
            "evidence_public_id": str(item.public_id),
            "reason": "content_changed",
            "previous_reviewed_at": previous_at.isoformat(),
            "previous_reviewed_by_user_id": str(previous_by) if previous_by else None,
        },
    )


async def invalidate_document_reviews(session, field, document_id, actor_user_id) -> None:
    """Caller holds the subject lock; invalidate in the content-update transaction."""
    items = list(
        await session.scalars(
            select(VerificationRequestEvidence)
            .where(
                getattr(VerificationRequestEvidence, field) == document_id,
            )
            .execution_options(populate_existing=True)
        )
    )
    for item in items:
        if item.reviewed_at is not None:
            request = await session.get(VerificationRequest, item.verification_request_id)
            await invalidate_review(session, request, item, actor_user_id)


async def record_evidence_review(session, request, item, actor_user_id) -> None:
    if item.reviewed_at is not None:
        return
    if item not in await applicable_evidence(session, request):
        raise ConflictError("Evidence is not currently applicable to this case")
    for model, document_id in (
        (EmploymentDocument, item.employment_document_id),
        (EducationDocument, item.education_document_id),
        (UserDocument, item.document_id),
    ):
        if document_id is not None:
            document = await session.get(model, document_id, populate_existing=True)
            if not document.checksum_sha256 or document.checksum_sha256 == "0" * 64:
                raise ConflictError("Evidence upload is not complete")
    item.reviewed_at = datetime.now(UTC)
    item.reviewed_by_user_id = actor_user_id
    await VerificationRequestWorkflowService(VerificationRequestRepository(session)).record_action(
        request,
        actor_user_id=actor_user_id,
        event_type="evidence_reviewed",
        event_source=VerificationRequestEventSource.ADMIN,
        metadata={
            "evidence_public_id": str(item.public_id),
            "reviewed_at": item.reviewed_at.isoformat(),
        },
    )
