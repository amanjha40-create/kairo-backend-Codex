"""Legacy entry point must use current canonical finalization, never shortcut it."""

import asyncio
from dataclasses import replace
from datetime import date
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.services import get_verification_request_admin_review_service
from app.db.session import engine
from app.exceptions import ConflictError, ForbiddenError, ValidationAppError
from app.main import app
from app.models import Employment, User, VerificationRequest
from app.models.verification_request_event import VerificationRequestEvent
from app.models.verification_review_note import VerificationReviewNote
from app.schemas.admin_review_workflow import (
    AdminReviewDirectConfirmationRequest,
    AdminReviewFinalizationRequest,
)
from app.services.evidence_review import lock_evidence_case
from app.services.verification_request_admin_review_service import (
    VerificationRequestAdminReviewService,
)
from app.services.verification_request_service import VerificationRequestService
from tests.test_admin_evidence_review import evidence_case as evidence_case  # noqa: F401
from tests.test_admin_evidence_review import events, review
from tests.test_admin_review_workflow import _override_current_user_factory


def payload():
    return AdminReviewDirectConfirmationRequest(
        confirmation_method="phone",
        confirmed_by="Synthetic private confirmer",
        verifier_role="Synthetic private role",
        contact_detail_used="synthetic-private@example.invalid",
        confirmation_outcome="details_confirmed",
        internal_note="Synthetic confirmation",
    )


async def confirm(c):
    return await c.svc.direct_confirm(c.admin.id, c.request.public_id, payload())


async def no_effects(c, before):
    assert [e.public_id for e in await events(c)] == before
    assert c.emp.verification_status == "draft"
    assert not list(await c.db.scalars(select(VerificationReviewNote)))
    c.svc._notify_finalization.assert_not_awaited()


@pytest.mark.parametrize(
    "state",
    [
        "pending_admin_review",
        "pending_admin_re_review",
        "approved_for_organization_verification",
        "pending_organization_resolution",
        "pending_organization_acceptance",
        "in_progress",
        "rejected",
        "cancelled",
    ],
)
async def test_early_and_conflicting_states_have_no_side_effects(evidence_case, state):
    c = evidence_case
    c.request.status = state
    await c.db.flush()
    with pytest.raises(ConflictError, match="not awaiting final quality review"):
        await confirm(c)
    await no_effects(c, [])


@pytest.mark.parametrize("count", [0, 1])
async def test_incomplete_inspection_never_finalizes(evidence_case, count):
    c = evidence_case
    for i in range(count):
        await review(c, i)
    before = [e.public_id for e in await events(c)]
    with pytest.raises(ValidationAppError) as exc:
        await confirm(c)
    assert exc.value.code == "evidence_review_incomplete"
    await no_effects(c, before)


@pytest.mark.parametrize("direct", [False, True])
async def test_equivalent_canonical_result_and_idempotency(evidence_case, direct):
    c = evidence_case
    for i in range(2):
        await review(c, i)
    if direct:
        first = await confirm(c)
        second = await confirm(c)
    else:
        body = AdminReviewFinalizationRequest(
            outcome="verified", decision_summary=payload().internal_note
        )
        first = await c.svc.finalize(c.admin.id, c.request.public_id, body)
        second = await c.svc.finalize(c.admin.id, c.request.public_id, body)
    assert first == second
    assert first.status == "verified" and c.emp.verification_status == "verified"
    c.svc._notify_finalization.assert_awaited_once()
    recorded = await events(c)
    kinds = [e.event_type for e in recorded]
    assert kinds.count("verification_request_admin_finalized") == 1
    assert kinds.count("trust_score_recalculation_requested") == 1
    assert "verification_request_manual_direct_confirmation" not in kinds
    notes = list(await c.db.scalars(select(VerificationReviewNote)))
    assert len(notes) == int(direct)
    if direct:
        assert notes[0].visibility == "internal"
        assert notes[0].metadata_payload["contact_detail_used"] == payload().contact_detail_used
        assert notes[0].author_user_id == c.admin.id
        timeline = await VerificationRequestService(c.db).get_timeline(
            c.owner.id, c.owner.email, c.request.public_id
        )
        assert payload().contact_detail_used not in timeline.model_dump_json()
        assert payload().confirmed_by not in timeline.model_dump_json()
        assert payload().internal_note not in timeline.model_dump_json()
    latest = await c.svc._reviews.get_latest_review_for_request(c.request.id)
    assert latest.decision_by_user_id == c.admin.id and latest.decision_at


async def test_zero_applicable_evidence_retains_canonical_behavior(evidence_case):
    c = evidence_case
    for item in c.items:
        item.status = "superseded"
    await c.db.flush()
    assert (await confirm(c)).status == "verified"


@pytest.mark.parametrize("role", ["user", "support", "moderator", "hr"])
async def test_service_permission_guard(evidence_case, role):
    c = evidence_case
    c.admin.role = role
    await c.db.flush()
    with pytest.raises(ForbiddenError):
        await confirm(c)
    await no_effects(c, [])


async def test_discrepancy_rejected_without_side_effects(evidence_case):
    c = evidence_case
    body = payload().model_copy(
        update={"confirmation_outcome": "details_confirmed_with_discrepancy"}
    )
    with pytest.raises(ConflictError):
        await c.svc.direct_confirm(c.admin.id, c.request.public_id, body)
    await no_effects(c, [])


async def test_stale_orm_state_is_reloaded_under_canonical_lock(evidence_case):
    c = evidence_case
    await c.db.execute(
        update(VerificationRequest)
        .where(VerificationRequest.id == c.request.id)
        .values(status="rejected")
        .execution_options(synchronize_session=False)
    )
    assert c.request.status == "pending_admin_quality_review"
    with pytest.raises(ConflictError):
        await confirm(c)
    assert c.request.status == "rejected"
    await no_effects(c, [])


async def test_replaced_evidence_review_cannot_be_reused(evidence_case):
    from app.schemas.verification_request import VerificationRequestEvidenceUpdateRequest

    c = evidence_case
    await review(c, 0)
    await review(c, 1)
    c.request.status = "awaiting_subject_corrections"
    await c.db.flush()
    await VerificationRequestService(c.db).update_evidence(
        c.owner.id,
        c.owner.email,
        c.request.public_id,
        c.items[0].public_id,
        VerificationRequestEvidenceUpdateRequest(value={"replacement": True}),
    )
    c.request.status = "pending_admin_quality_review"
    await c.db.flush()
    with pytest.raises(ValidationAppError, match="1/2"):
        await confirm(c)
    c.svc._notify_finalization.assert_not_awaited()


@pytest.mark.parametrize(
    "role,count,expected",
    [("admin", 2, 200), ("superadmin", 2, 200), ("admin", 0, 400), ("hr", 2, 403)],
)
async def test_legacy_http_contract(evidence_case, role, count, expected):
    c = evidence_case
    for i in range(count):
        await review(c, i)
    c.admin.role = role
    await c.db.flush()
    current = replace(await _override_current_user_factory(role)(), id=c.admin.id)
    app.dependency_overrides[get_current_user] = lambda: current
    app.dependency_overrides[get_verification_request_admin_review_service] = lambda: c.svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            result = await client.post(
                f"/api/v1/admin/verification-requests/{c.request.public_id}/direct-confirmation",
                json=payload().model_dump(),
            )
        assert result.status_code == expected
        if expected == 200:
            assert result.json()["status"] == "verified"
        else:
            c.svc._notify_finalization.assert_not_awaited()
    finally:
        app.dependency_overrides.clear()


async def test_concurrent_conflicting_finalization_is_rejected():
    assert engine.url.host in {"localhost", "127.0.0.1"}
    async with AsyncSession(engine, expire_on_commit=False) as db:
        actor = User(email=f"rc-race-{uuid4()}@example.invalid", role="admin", is_active=True)
        db.add(actor)
        await db.flush()
        emp = Employment(
            created_by_user_id=actor.id,
            subject_full_name="Synthetic",
            employer_legal_name="Synthetic",
            job_title="QA",
            start_date=date(2024, 1, 1),
            verification_status="draft",
        )
        db.add(emp)
        await db.flush()
        request = VerificationRequest(
            subject_user_id=actor.id,
            requested_by_user_id=actor.id,
            subject_name="Synthetic",
            subject_email=actor.email,
            employment_id=emp.id,
            request_type="employment",
            status="pending_admin_quality_review",
        )
        db.add(request)
        await db.commit()
    notification = AsyncMock()
    started = asyncio.Event()

    async def direct():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            svc = VerificationRequestAdminReviewService(db)
            svc._notify_finalization = notification
            started.set()
            return await svc.direct_confirm(actor.id, request.public_id, payload())

    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            row = await lock_evidence_case(db, request.public_id)
            row.status = "rejected"
            await db.flush()
            task = asyncio.create_task(direct())
            await started.wait()
            await asyncio.sleep(0.05)
            assert not task.done()
            await db.commit()
            with pytest.raises(ConflictError):
                await task
        notification.assert_not_awaited()
        async with AsyncSession(engine) as db:
            assert not list(
                await db.scalars(
                    select(VerificationRequestEvent).where(
                        VerificationRequestEvent.verification_request_id == request.id
                    )
                )
            )
    finally:
        async with AsyncSession(engine) as db:
            await db.execute(
                delete(VerificationRequest).where(VerificationRequest.id == request.id)
            )
            await db.execute(delete(Employment).where(Employment.id == emp.id))
            await db.execute(delete(User).where(User.id == actor.id))
            await db.commit()


@pytest.mark.parametrize("kind", ["employment", "education", "vault"])
@pytest.mark.parametrize("invalid", [False, True])
async def test_restored_download_preserves_case_binding(evidence_case, monkeypatch, kind, invalid):
    from app.models.education import Education
    from app.models.education_document import EducationDocument
    from app.models.employment_document import EmploymentDocument
    from app.models.user_document import UserDocument

    c = evidence_case
    fields = dict(
        document_type="other",
        object_key="synthetic/rc.pdf",
        original_filename="synthetic.pdf",
        content_type="application/pdf",
        byte_size=10,
        checksum_sha256="a" * 64,
    )
    if kind == "employment":
        doc = EmploymentDocument(employment_id=c.emp.id, uploaded_by_user_id=c.owner.id, **fields)
        field = "employment_document_id"
    elif kind == "education":
        parent = Education(user_id=c.owner.id, institution_name="Synthetic", degree="Synthetic")
        c.db.add(parent)
        await c.db.flush()
        c.request.education_id = parent.id
        c.request.employment_id = None
        c.request.request_type = "education"
        doc = EducationDocument(education_id=parent.id, uploaded_by_user_id=c.owner.id, **fields)
        field = "education_document_id"
    else:
        doc = UserDocument(user_id=c.owner.id if not invalid else c.second.id, **fields)
        field = "document_id"
    c.db.add(doc)
    await c.db.flush()
    setattr(c.items[0], field, doc.id)
    if invalid and kind != "vault":
        c.items[0].status = "superseded"
    await c.db.flush()
    presign = AsyncMock(return_value="https://synthetic.invalid/short-lived")
    monkeypatch.setattr(
        "app.services.verification_request_service.generate_presigned_get_url", presign
    )
    c.svc._settings = c.svc._settings.model_copy(update={"s3_documents_bucket": "synthetic-rc"})
    if invalid:
        with pytest.raises(ConflictError):
            await c.svc.get_evidence_download_url(c.request.public_id, c.items[0].public_id)
        presign.assert_not_awaited()
    else:
        result = await c.svc.get_evidence_download_url(c.request.public_id, c.items[0].public_id)
        assert result.expires_in_seconds == 300
        presign.assert_awaited_once()


async def test_admin_actor_projection_does_not_expand_candidate_schema(evidence_case):
    from app.schemas.verification_request import VerificationRequestTimelineEventResponse

    c = evidence_case
    c.admin.full_name = "Synthetic Admin"
    await c.db.flush()
    await review(c)
    timeline = await c.svc.get_timeline(c.request.public_id)
    assert timeline.timeline.items[0].actor_display_name == c.admin.full_name
    assert timeline.timeline.items[0].actor_email == c.admin.email
    assert "actor_email" not in VerificationRequestTimelineEventResponse.model_fields
