"""Shared evidence policy; callers hold the employment lock while mutating/submitting."""

from sqlalchemy import func, select

from app.exceptions import ConflictError
from app.models.employment_document import EmploymentDocument

PRIMARY_DOCUMENT_TYPES = frozenset({
    "relieving_letter", "employment_contract", "offer_letter", "payslip", "pay_stub",
    "appointment_letter", "experience_letter", "contract", "hr_letter",
})


async def assert_evidence_editable(session, employment_id):
    from app.repositories.verification_request import VerificationRequestRepository

    request = await VerificationRequestRepository(session).get_active_for_employment(employment_id)
    if request is not None and request.status not in {
        "pending_subject_submission",
        "accepted",
        "awaiting_subject_corrections",
    }:
        raise ConflictError("Employment evidence is locked during verification")


async def primary_evidence_count(session, employment_id, owner_id, document_ids=None):
    document = EmploymentDocument
    query = select(func.count(func.distinct(document.id))).where(
        document.employment_id == employment_id,
        document.uploaded_by_user_id == owner_id,
        document.deleted_at.is_(None),
        document.evidence_role == "primary",
        document.document_type.in_(PRIMARY_DOCUMENT_TYPES),
        document.verification_status.in_(("pending_review", "approved", "rejected")),
        document.checksum_sha256 != "0" * 64,
        func.length(document.checksum_sha256) == 64,
    )
    if document_ids is not None:
        query = query.where(document.id.in_(set(document_ids)))
    return int(await session.scalar(query) or 0)


async def require_primary_evidence(session, employment_id, owner_id, document_ids=None):
    count = await primary_evidence_count(session, employment_id, owner_id, document_ids)
    if count < 2:
        raise ConflictError(
            "Add at least 2 completed primary employment documents before continuing.",
        )
    return count
