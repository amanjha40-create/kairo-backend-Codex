"""Authoritative inspection and replacement lifecycle on isolated Postgres."""

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.services import get_verification_request_admin_review_service
from app.db.session import engine
from app.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.main import app
from app.models import Employment, User, VerificationRequest
from app.models.employment_document import EmploymentDocument
from app.models.verification_request_event import VerificationRequestEvent
from app.models.verification_request_evidence import VerificationRequestEvidence
from app.schemas.admin_review_workflow import AdminReviewFinalizationRequest
from app.schemas.verification_request import VerificationRequestEvidenceUpdateRequest
from app.services.evidence_review import (
    applicable_evidence,
    lock_evidence_case,
    require_evidence_review_complete,
)
from app.services.verification_request_admin_review_service import (
    VerificationRequestAdminReviewService,
)
from app.services.verification_request_service import VerificationRequestService


@pytest.fixture
async def evidence_case():
    assert engine.url.host in {"localhost", "127.0.0.1"}
    async with engine.connect() as conn:
        outer = await conn.begin()
        async with AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as db:
            owner = User(email=f"qa-{uuid4()}@example.com", role="user", is_active=True)
            admin = User(email=f"admin-{uuid4()}@example.com", role="admin", is_active=True)
            second = User(email=f"admin2-{uuid4()}@example.com", role="admin", is_active=True)
            db.add_all([owner, admin, second])
            await db.flush()
            emp = Employment(
                created_by_user_id=owner.id,
                subject_full_name="Synthetic QA",
                subject_email=owner.email,
                employer_legal_name="Synthetic QA",
                job_title="QA",
                employment_type="full_time",
                start_date=date(2024, 1, 1),
                verification_method="employer_confirmation",
                verification_status="draft",
            )
            db.add(emp)
            await db.flush()
            request = VerificationRequest(
                subject_user_id=owner.id,
                requested_by_user_id=owner.id,
                subject_name="Synthetic QA",
                subject_email=owner.email,
                employment_id=emp.id,
                request_type="employment",
                status="pending_admin_quality_review",
            )
            db.add(request)
            await db.flush()
            items = [
                VerificationRequestEvidence(
                    verification_request_id=request.id,
                    submitted_by_user_id=owner.id,
                    evidence_type="statement",
                    field_key=f"field_{i}",
                    value={"synthetic": i},
                    status="submitted",
                )
                for i in range(2)
            ]
            db.add_all(items)
            await db.flush()
            svc = VerificationRequestAdminReviewService(db)
            svc._notify_finalization = AsyncMock()
            yield SimpleNamespace(
                db=db,
                request=request,
                items=items,
                owner=owner,
                admin=admin,
                second=second,
                emp=emp,
                svc=svc,
            )
        await outer.rollback()


async def events(c):
    return list(
        (
            await c.db.scalars(
                select(VerificationRequestEvent).where(
                    VerificationRequestEvent.verification_request_id == c.request.id
                )
            )
        ).all()
    )


async def review(c, index=0, actor=None):
    return await c.svc.review_evidence(
        actor or c.admin.id, c.request.public_id, c.items[index].public_id
    )


@pytest.mark.asyncio
async def test_review_persists_is_idempotent_and_preserves_disposition(evidence_case):
    c = evidence_case
    assert c.items[0].reviewed_at is None and c.items[0].reviewed_by_user_id is None
    before = await c.svc._to_admin_evidence_response(c.items[0])
    assert not before.reviewed and before.reviewed_at is None
    first = await review(c)
    duplicate = await review(c, actor=c.second.id)
    assert first == duplicate
    assert first.reviewed and first.reviewed_at and first.reviewed_by_user_id == c.admin.id
    assert c.items[0].status == "submitted"
    after = await c.svc._to_admin_evidence_response(c.items[0])
    assert after.reviewed and after.reviewed_at == first.reviewed_at
    assert [e.event_type for e in await events(c)] == ["evidence_reviewed"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        "verified",
        "rejected",
        "cancelled",
        "expired",
        "withdrawn_by_candidate",
        "awaiting_subject_corrections",
    ],
)
async def test_closed_or_nonreview_state_rejected(evidence_case, status):
    c = evidence_case
    c.request.status = status
    await c.db.flush()
    with pytest.raises(ConflictError):
        await review(c)
    assert not await events(c)


@pytest.mark.asyncio
async def test_wrong_case_missing_and_candidate_rejected(evidence_case):
    c = evidence_case
    with pytest.raises(ForbiddenError):
        await review(c, actor=c.owner.id)
    with pytest.raises(NotFoundError):
        await c.svc.review_evidence(c.admin.id, c.request.public_id, uuid4())
    other = VerificationRequest(
        subject_user_id=c.owner.id,
        requested_by_user_id=c.owner.id,
        subject_name="Other",
        subject_email=c.owner.email,
        request_type="employment",
        status="pending_admin_quality_review",
    )
    c.db.add(other)
    await c.db.flush()
    with pytest.raises(NotFoundError):
        await c.svc.review_evidence(c.admin.id, other.public_id, c.items[0].public_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 1, 2])
async def test_finalization_uses_current_review_state(evidence_case, count):
    c = evidence_case
    for i in range(count):
        await review(c, i)
    payload = AdminReviewFinalizationRequest(
        outcome="verified", decision_summary="Synthetic review"
    )
    if count < 2:
        with pytest.raises(ValidationAppError) as exc:
            await c.svc.finalize(c.admin.id, c.request.public_id, payload)
        assert exc.value.code == "evidence_review_incomplete"
        assert f"{count}/2" in exc.value.message
        assert c.emp.verification_status == "draft"
        c.svc._notify_finalization.assert_not_awaited()
    else:
        result = await c.svc.finalize(c.admin.id, c.request.public_id, payload)
        assert result.status == "verified"
        assert c.emp.verification_status == "verified"


@pytest.mark.asyncio
async def test_replacement_invalidates_atomically_and_retry_does_not_duplicate(evidence_case):
    c = evidence_case
    await review(c, 0)
    await review(c, 1)
    await require_evidence_review_complete(c.db, c.request)
    c.request.status = "awaiting_subject_corrections"
    await c.db.flush()
    svc = VerificationRequestService(c.db)
    payload = VerificationRequestEvidenceUpdateRequest(value={"synthetic": "replacement"})
    await svc.update_evidence(
        c.owner.id, c.owner.email, c.request.public_id, c.items[0].public_id, payload
    )
    await svc.update_evidence(
        c.owner.id, c.owner.email, c.request.public_id, c.items[0].public_id, payload
    )
    assert c.items[0].reviewed_at is None and c.items[0].reviewed_by_user_id is None
    assert not (await c.svc._to_admin_evidence_response(c.items[0])).reviewed
    event_types = [e.event_type for e in await events(c)]
    assert event_types.count("evidence_reviewed") == 2
    assert event_types.count("evidence_review_invalidated") == 1
    c.request.status = "pending_admin_quality_review"
    await c.db.flush()
    with pytest.raises(ValidationAppError, match="1/2"):
        await c.svc.finalize(
            c.admin.id,
            c.request.public_id,
            AdminReviewFinalizationRequest(outcome="verified", decision_summary="Synthetic"),
        )
    await review(c)
    await require_evidence_review_complete(c.db, c.request)
    assert [e.event_type for e in await events(c)].count("evidence_reviewed") == 3


@pytest.mark.asyncio
async def test_failed_replacement_and_noncontent_changes_preserve_review(evidence_case):
    c = evidence_case
    original = await review(c)
    c.request.status = "awaiting_subject_corrections"
    await c.db.flush()
    svc = VerificationRequestService(c.db)
    with pytest.raises(NotFoundError):
        await svc.update_evidence(
            c.owner.id,
            c.owner.email,
            c.request.public_id,
            c.items[0].public_id,
            VerificationRequestEvidenceUpdateRequest(document_id=uuid4()),
        )
    assert c.items[0].reviewed_at == original.reviewed_at
    c.items[0].status = "rejected"
    c.items[0].updated_at = datetime.now(UTC)
    await c.db.flush()
    state = await c.svc._to_admin_evidence_response(c.items[0])
    assert state.reviewed and state.status == "rejected"
    assert not any(e.event_type == "evidence_review_invalidated" for e in await events(c))


@pytest.mark.asyncio
async def test_superseded_deleted_and_wrong_parent_excluded_zero_preserved(evidence_case):
    c = evidence_case
    c.items[0].status = "superseded"
    doc = EmploymentDocument(
        employment_id=c.emp.id,
        uploaded_by_user_id=c.owner.id,
        document_type="other",
        object_key=f"synthetic/{uuid4()}",
        original_filename="synthetic.pdf",
        content_type="application/pdf",
        byte_size=10,
        checksum_sha256="a" * 64,
        verification_status="uploaded",
        deleted_at=datetime.now(UTC),
    )
    c.db.add(doc)
    await c.db.flush()
    c.items[1].employment_document_id = doc.id
    await c.db.flush()
    assert await applicable_evidence(c.db, c.request) == []
    await require_evidence_review_complete(c.db, c.request)
    with pytest.raises(ConflictError):
        await review(c, 0)
    with pytest.raises(ConflictError):
        await review(c, 1)
    result = await c.svc.finalize(
        c.admin.id,
        c.request.public_id,
        AdminReviewFinalizationRequest(
            outcome="verified", decision_summary="Synthetic zero applicable"
        ),
    )
    assert result.status == "verified"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["education", "vault"])
async def test_underlying_file_completion_invalidates_same_row_review(evidence_case, kind):
    from app.models.education import Education
    from app.models.education_document import EducationDocument
    from app.models.user_document import UserDocument
    from app.services.education_service import EducationService
    from app.services.user_document_service import UserDocumentService

    c = evidence_case
    common = dict(
        document_type="other",
        object_key=f"synthetic/{uuid4()}",
        original_filename="synthetic.pdf",
        content_type="application/pdf",
        byte_size=10,
        checksum_sha256="a" * 64,
    )
    if kind == "education":
        education = Education(user_id=c.owner.id, institution_name="Synthetic", degree="Synthetic")
        c.db.add(education)
        await c.db.flush()
        c.request.education_id = education.id
        c.request.employment_id = None
        c.request.request_type = "education"
        doc = EducationDocument(education_id=education.id, uploaded_by_user_id=c.owner.id, **common)
    else:
        doc = UserDocument(user_id=c.owner.id, **common)
    c.db.add(doc)
    await c.db.flush()
    if kind == "education":
        c.items[0].education_document_id = doc.id
        complete = lambda checksum: EducationService(c.db).complete_document_upload(
            c.owner.id, education.id, doc.id, checksum
        )
    else:
        c.items[0].document_id = doc.id
        complete = lambda checksum: UserDocumentService(c.db).complete_upload(
            c.owner.id, doc.id, checksum
        )
    await c.db.flush()
    await review(c)
    await complete("a" * 64)
    assert c.items[0].reviewed_at is not None
    await complete("b" * 64)
    await complete("b" * 64)
    assert c.items[0].reviewed_at is None and c.items[0].reviewed_by_user_id is None
    assert doc.checksum_sha256 == "b" * 64
    assert [e.event_type for e in await events(c)].count("evidence_review_invalidated") == 1


@pytest.mark.asyncio
async def test_upload_incomplete_cannot_be_marked_reviewed(evidence_case):
    c = evidence_case
    doc = EmploymentDocument(
        employment_id=c.emp.id,
        uploaded_by_user_id=c.owner.id,
        document_type="other",
        object_key=f"synthetic/{uuid4()}",
        original_filename="synthetic.pdf",
        content_type="application/pdf",
        byte_size=10,
        checksum_sha256="0" * 64,
        verification_status="pending_upload",
    )
    c.db.add(doc)
    await c.db.flush()
    c.items[0].employment_document_id = doc.id
    await c.db.flush()
    with pytest.raises(ConflictError, match="upload is not complete"):
        await review(c)
    with pytest.raises(ValidationAppError, match="0/2"):
        await require_evidence_review_complete(c.db, c.request)


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_content_and_review(evidence_case, monkeypatch):
    c = evidence_case
    original = await review(c)
    c.request.status = "awaiting_subject_corrections"
    await c.db.flush()
    item_id = c.items[0].id
    original_value = dict(c.items[0].value)
    from app.services.verification_request_workflow_service import (
        VerificationRequestWorkflowService,
    )

    monkeypatch.setattr(
        VerificationRequestWorkflowService,
        "record_action",
        AsyncMock(side_effect=RuntimeError("synthetic audit failure")),
    )
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        async with c.db.begin_nested():
            await VerificationRequestService(c.db).update_evidence(
                c.owner.id,
                c.owner.email,
                c.request.public_id,
                c.items[0].public_id,
                VerificationRequestEvidenceUpdateRequest(value={"synthetic": "rollback"}),
            )
    item = await c.db.get(VerificationRequestEvidence, item_id, populate_existing=True)
    assert item.value == original_value
    assert item.reviewed_at == original.reviewed_at
    assert item.reviewed_by_user_id == original.reviewed_by_user_id
    assert not any(e.event_type == "evidence_review_invalidated" for e in await events(c))


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["user", "hr", "support", "moderator"])
async def test_route_permission_rejects_non_admin(role):
    from tests.test_admin_review_workflow import _override_current_user_factory

    app.dependency_overrides[get_current_user] = _override_current_user_factory(role)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/admin/verification-requests/{uuid4()}/evidence/{uuid4()}/review"
            )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_direct_http_finalization_cannot_bypass(evidence_case):
    c = evidence_case
    from tests.test_admin_review_workflow import _override_current_user_factory

    app.dependency_overrides[get_current_user] = _override_current_user_factory("admin")
    app.dependency_overrides[get_verification_request_admin_review_service] = lambda: c.svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/admin/verification-requests/{c.request.public_id}/finalize",
                json={"outcome": "verified", "decision_summary": "Synthetic"},
            )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "evidence_review_incomplete"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("finalize_first", [False, True])
async def test_concurrent_review_and_case_lock_serialize(finalize_first):
    assert engine.url.host in {"localhost", "127.0.0.1"}
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        actor = User(email=f"race-{uuid4()}@example.com", role="admin", is_active=True)
        setup.add(actor)
        await setup.flush()
        request = VerificationRequest(
            subject_user_id=actor.id,
            requested_by_user_id=actor.id,
            subject_name="Synthetic",
            subject_email=actor.email,
            request_type="employment",
            status="pending_admin_quality_review",
        )
        setup.add(request)
        await setup.flush()
        item = VerificationRequestEvidence(
            verification_request_id=request.id,
            submitted_by_user_id=actor.id,
            evidence_type="statement",
            field_key="synthetic",
            value={"synthetic": True},
            status="submitted",
        )
        setup.add(item)
        await setup.commit()

    async def perform_review():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            return await VerificationRequestAdminReviewService(db).review_evidence(
                actor.id, request.public_id, item.public_id
            )

    try:
        if finalize_first:
            async with AsyncSession(engine, expire_on_commit=False) as db:
                current = await lock_evidence_case(db, request.public_id)
                current.status = "verified"
                await db.flush()
                task = asyncio.create_task(perform_review())
                await asyncio.sleep(0.05)
                assert not task.done()
                await db.commit()
                with pytest.raises(ConflictError):
                    await task
        else:
            one, two = await asyncio.gather(perform_review(), perform_review())
            assert one == two
        async with AsyncSession(engine) as db:
            recorded = list(
                await db.scalars(
                    select(VerificationRequestEvent).where(
                        VerificationRequestEvent.verification_request_id == request.id
                    )
                )
            )
            assert len(recorded) == (0 if finalize_first else 1)
    finally:
        async with AsyncSession(engine) as db:
            await db.execute(
                delete(VerificationRequest).where(VerificationRequest.id == request.id)
            )
            await db.execute(delete(User).where(User.id == actor.id))
            await db.commit()


@pytest.mark.asyncio
async def test_http_admin_review_returns_safe_metadata(evidence_case):
    c = evidence_case
    from tests.test_admin_review_workflow import _override_current_user_factory

    current = await _override_current_user_factory("admin")()
    current = replace(current, id=c.admin.id)
    app.dependency_overrides[get_current_user] = lambda: current
    app.dependency_overrides[get_verification_request_admin_review_service] = lambda: c.svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/admin/verification-requests/{c.request.public_id}/evidence/{c.items[0].public_id}/review"
            )
        assert response.status_code == 200
        assert set(response.json()) == {
            "evidence_public_id",
            "reviewed",
            "reviewed_at",
            "reviewed_by_user_id",
        }
    finally:
        app.dependency_overrides.clear()


def test_candidate_evidence_schemas_do_not_expose_review_provenance():
    from app.schemas.verification_request import (
        VerificationRequestEvidenceCreateRequest,
        VerificationRequestEvidenceResponse,
    )

    for schema in (
        VerificationRequestEvidenceCreateRequest,
        VerificationRequestEvidenceUpdateRequest,
        VerificationRequestEvidenceResponse,
    ):
        assert (
            not {"reviewed", "reviewed_at", "reviewed_by_user_id", "review_applicable"}
            & schema.model_fields.keys()
        )


@pytest.mark.asyncio
async def test_unauthenticated_review_is_rejected():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/admin/verification-requests/{uuid4()}/evidence/{uuid4()}/review"
        )
    assert response.status_code == 401
