"""Employment evidence role policy against the migrated disposable test database."""

from datetime import UTC, date, datetime
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import engine
from app.exceptions import ConflictError, EmploymentCaseNotFoundError, EmploymentWorkflowError, NotFoundError
from app.models.employment import Employment
from app.models.employment_document import EmploymentDocument
from app.models.user import User
from app.schemas.employment.requests import ClassifyEmploymentEvidenceRequest, UploadDocumentRequest
from app.services.employment_document_service import EmploymentDocumentService
from app.services.employment_evidence_eligibility import (
    primary_evidence_count,
    require_primary_evidence,
)
from app.services.document_upload_service import DocumentUploadService
from app.services.verification_request_service import VerificationRequestService
from app.schemas.verification_request import VerificationRequestSubmitForReviewRequest
from app.verification_requests.enums import VerificationRequestStatus, VerificationRequestType


@pytest.fixture
async def case():
    async with engine.connect() as conn:
        outer = await conn.begin()
        async with AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as session:
            user = User(email=f"{uuid4()}@example.test", role="user", is_active=True)
            other = User(email=f"{uuid4()}@example.test", role="user", is_active=True)
            session.add_all([user, other])
            await session.flush()
            emp = Employment(
                created_by_user_id=user.id,
                subject_full_name="Synthetic QA",
                employer_legal_name="Synthetic Employer",
                job_title="Engineer",
                employment_type="full_time",
                start_date=date(2024, 1, 1),
                work_location_country="IN",
                verification_method="document",
                verification_status="draft",
            )
            session.add(emp)
            await session.flush()
            yield session, user, other, emp
        await outer.rollback()


async def document(case, role=None, **overrides):
    session, user, _, emp = case
    values = dict(
        employment_id=emp.id,
        uploaded_by_user_id=user.id,
        document_type="payslip",
        object_key=f"synthetic/{uuid4()}",
        original_filename="synthetic.pdf",
        content_type="application/pdf",
        byte_size=10,
        checksum_sha256=uuid4().hex * 2,
        verification_status="pending_review",
        extraction_status="skipped",
        evidence_role=role,
    )
    values.update(overrides)
    row = EmploymentDocument(**values)
    session.add(row)
    await session.flush()
    return row


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 1, 2, 3])
async def test_primary_threshold_same_category(case, count):
    session, user, _, emp = case
    rows = [await document(case, "primary") for _ in range(count)]
    ids = [row.id for row in rows] * 2
    assert await primary_evidence_count(session, emp.id, user.id, ids) == count
    if count < 2:
        with pytest.raises(ConflictError):
            await require_primary_evidence(session, emp.id, user.id, ids)
    else:
        assert await require_primary_evidence(session, emp.id, user.id, ids) == count


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"evidence_role": None},
        {"evidence_role": "supporting"},
        {"verification_status": "pending_upload"},
        {"verification_status": "failed"},
        {"deleted_at": datetime.now(UTC)},
        {"checksum_sha256": "0" * 64},
        {"document_type": "other"},
        {"document_type": "government_id"},
        {"document_type": "bank_statement"},
        {"document_type": "form_w2"},
        {"document_type": "form_1099"},
        {"document_type": "employment_id_card"},
    ],
)
async def test_ineligible_files_never_count(case, overrides):
    session, user, _, emp = case
    await document(case, "primary")
    for _ in range(5):
        await document(case, **({"role": "primary"} | overrides))
    assert await primary_evidence_count(session, emp.id, user.id) == 1
    with pytest.raises(ConflictError):
        await require_primary_evidence(session, emp.id, user.id)


@pytest.mark.asyncio
async def test_detached_and_cross_owner_do_not_count(case):
    session, user, other, emp = case
    first = await document(case, "primary")
    await document(case, "primary")
    await document(case, "primary", uploaded_by_user_id=other.id)
    assert await primary_evidence_count(session, emp.id, user.id, [first.id, first.id]) == 1
    assert await primary_evidence_count(session, uuid4(), user.id) == 0


@pytest.mark.asyncio
async def test_valid_types_and_legacy_visibility(case):
    session, user, _, emp = case
    await document(case, "primary", document_type="offer_letter")
    await document(case, "primary", document_type="relieving_letter")
    legacy = await document(case, "primary", document_type="government_id")
    assert await require_primary_evidence(session, emp.id, user.id) == 2
    service = EmploymentDocumentService(session, get_settings())
    rows, total = await service.list_for_employment_owned(user.id, emp.id, offset=0, limit=10)
    assert total == 3 and legacy.id in {row.id for row in rows}
    await session.refresh(legacy)
    assert legacy.evidence_role == "primary"


@pytest.mark.asyncio
async def test_government_id_unavailable_for_new_uploads(case):
    session, user, _, emp = case
    service = EmploymentDocumentService(session, get_settings())
    assert "government_id" not in {item.value for item in service.get_upload_options().document_types}
    payload = UploadDocumentRequest(document_type="government_id", original_filename="synthetic.pdf",
                                    content_type="application/pdf", byte_size=10, evidence_role="primary")
    with pytest.raises(EmploymentWorkflowError):
        await service.create_upload_intent(user.id, emp.id, payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["primary", "supporting"])
async def test_owner_classifies_legacy_without_reupload(case, role):
    session, user, _, emp = case
    row = await document(case)
    original = row.object_key, row.checksum_sha256, row.id
    svc = EmploymentDocumentService(session, get_settings())
    assert (await svc.eligibility(user.id, emp.id))["eligible_primary_count"] == 0
    response = await svc.classify_legacy(user.id, emp.id, row.id, role)
    assert response.evidence_role == role
    assert (row.object_key, row.checksum_sha256, row.id) == original
    assert (await svc.eligibility(user.id, emp.id))["eligible_primary_count"] == (role == "primary")
    assert (await svc.classify_legacy(user.id, emp.id, row.id, role)).evidence_role == role
    with pytest.raises(ConflictError):
        await svc.classify_legacy(
            user.id, emp.id, row.id, "supporting" if role == "primary" else "primary"
        )


@pytest.mark.asyncio
async def test_cross_user_and_locked_classification_rejected(case):
    session, user, other, emp = case
    row = await document(case)
    svc = EmploymentDocumentService(session, get_settings())
    with pytest.raises(EmploymentCaseNotFoundError):
        await svc.classify_legacy(other.id, emp.id, row.id, "primary")
    foreign = await document(case, uploaded_by_user_id=other.id)
    with pytest.raises(NotFoundError):
        await svc.classify_legacy(user.id, emp.id, foreign.id, "primary")
    emp.verification_status = "under_review"
    await session.flush()
    with pytest.raises(ConflictError):
        await svc.classify_legacy(user.id, emp.id, row.id, "primary")
    assert row.evidence_role is None


@pytest.mark.asyncio
async def test_database_rejects_invalid_role_and_legacy_stays_null(case):
    session, _, _, _ = case
    row = await document(case)
    assert (
        await session.scalar(
            select(EmploymentDocument.evidence_role).where(EmploymentDocument.id == row.id)
        )
        is None
    )
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await document(case, "invalid")


@pytest.mark.parametrize("role", [None, "invalid", "PRIMARY"])
def test_role_request_validation(role):
    with pytest.raises(ValidationError):
        ClassifyEmploymentEvidenceRequest(evidence_role=role)
    with pytest.raises(ValidationError):
        UploadDocumentRequest(
            document_type="payslip",
            original_filename="synthetic.pdf",
            content_type="application/pdf",
            byte_size=10,
            evidence_role=role,
        )


def test_upload_requires_explicit_role():
    with pytest.raises(ValidationError):
        UploadDocumentRequest(
            document_type="payslip",
            original_filename="synthetic.pdf",
            content_type="application/pdf",
            byte_size=10,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["primary", "supporting"])
async def test_upload_intent_persists_role_but_never_counts_pending(case, role):
    session, user, _, emp = case
    service = DocumentUploadService(
        session, get_settings().model_copy(update={"s3_documents_bucket": "synthetic"})
    )
    service._storage = SimpleNamespace(
        validate_declaration=lambda **kw: None,
        presign_put_url=AsyncMock(return_value=("https://example.invalid/upload", 300)),
    )
    result = await service.create_upload_intent(
        user.id,
        emp.id,
        UploadDocumentRequest(
            document_type="payslip",
            evidence_role=role,
            original_filename="synthetic.pdf",
            content_type="application/pdf",
            byte_size=10,
        ),
    )
    row = await session.get(EmploymentDocument, result.document_id)
    assert row.evidence_role == role
    assert row.verification_status == "pending_upload"
    assert await primary_evidence_count(session, emp.id, user.id) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 1, 2])
@pytest.mark.parametrize("resubmit", [False, True])
async def test_submit_and_resubmit_enforce_live_primary_attachment_count(case, count, resubmit):
    session, user, _, emp = case
    rows = [await document(case, "primary") for _ in range(count)]
    supporting = await document(case, "supporting")
    request = SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        employment_id=emp.id,
        request_type=VerificationRequestType.EMPLOYMENT,
        status=VerificationRequestStatus.AWAITING_SUBJECT_CORRECTIONS
        if resubmit
        else VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION,
    )
    service = VerificationRequestService(session, settings=get_settings())
    service._require_subject_request = AsyncMock(return_value=request)
    service._evidence = SimpleNamespace(
        list_for_request=AsyncMock(
            return_value=[
                SimpleNamespace(employment_document_id=row.id) for row in [*rows, supporting]
            ]
        )
    )
    service._contacts = SimpleNamespace(get_current=AsyncMock(return_value=object()))
    correction = SimpleNamespace(status="open")
    service._reviews = SimpleNamespace(
        list_reviews_for_request=AsyncMock(return_value=[]),
        list_open_corrections_for_request=AsyncMock(return_value=[correction]),
    )
    service._workflow = SimpleNamespace(transition=AsyncMock())
    service._apply_submission_consent = lambda *args: None
    service._capture_claim_snapshot = AsyncMock()
    service._notify_admin_review_needed = AsyncMock()
    service._commit_reload_subject_response = AsyncMock(return_value=request)
    request.consented_fields = []
    request.consented_evidence_scope = []
    request.consented_at = None
    request.consent_version = "v1"

    async def execute():
        if resubmit:
            return await service.resubmit(user.id, user.email, request.public_id)
        return await service.submit_for_review(
            user.id,
            user.email,
            request.public_id,
            VerificationRequestSubmitForReviewRequest(
                consent_version="v1",
                consented_fields=["employment.role"],
                consented_evidence_scope=["employment_evidence"],
            ),
        )

    if count < 2:
        with pytest.raises(ConflictError):
            await execute()
        service._workflow.transition.assert_not_awaited()
    else:
        assert await execute() is request
        service._workflow.transition.assert_awaited_once()
