from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.db.session import async_session_factory
from app.exceptions import ValidationAppError
from app.models.education import Education
from app.models.resume_document import ResumeDocument
from app.models.resume_parsed_result import ResumeParsedResult
from app.models.resume_processing_job import ResumeProcessingJob
from app.models.resume_review_item import ResumeReviewItem
from app.models.user import User
from app.resumes.education_review import normalize_education_review
from app.resumes.review_schemas import (
    ReviewImportRequest,
    ReviewItemUpdateRequest,
    ReviewValidateRequest,
    review_claim_adapter,
)
from app.services.resume_review_service import ResumeReviewService

BASE = {"claim_type": "education", "institution_name": "Synthetic Institute"}


@pytest.mark.parametrize("extra", [
    {"is_current": True},
    {"is_current": True, "start_date_display": "2020"},
    {"is_current": True, "end_date_display": "Present"},
    {"is_current": True, "end_date_precision": "year"},
    {"is_current": False, "end_date": "2020-12-31"},
    {"is_current": False, "end_date_display": "2020"},
    {"is_current": False, "end_date_display": "Jan 2020"},
    {"is_current": False, "end_date": "2020-12-31", "end_date_precision": "year"},
])
def test_valid_normalization_is_final_valid_and_idempotent(extra):
    payload = BASE | extra
    before = deepcopy(payload)
    result = normalize_education_review(payload)
    assert payload == before
    assert review_claim_adapter.validate_python(result)
    assert normalize_education_review(result) == result
    assert result["is_current"] == extra["is_current"]
    if extra["is_current"]:
        assert result["end_date"] is None
    if extra.get("end_date_precision"):
        assert result["end_date_precision"] == extra["end_date_precision"]


@pytest.mark.parametrize("extra,code", [
    ({"is_current": True, "end_date": "2020-01-01"}, "current_claim_has_end_date"),
    ({"is_current": True, "end_date_display": "2020"}, "current_claim_has_end_date"),
    ({"is_current": "true", "end_date_display": "2020"}, "current_claim_has_end_date"),
    ({"end_date": "private-invalid-date"}, "invalid_education_date"),
    ({"end_date_display": "private-invalid-date"}, "invalid_education_date"),
    ({"end_date_display": "0000"}, "invalid_education_date"),
    ({"end_date": 123}, "invalid_education_date"),
    ({"end_date": "2020-01-01", "start_date": "2021-01-01"}, "end_date_before_start_date"),
    ({"end_date": "2020-12-31", "end_date_display": "2021"}, "education_date_alias_conflict"),
    ({"end_date_display": "2020", "end_date_precision": "month"},
     "education_date_precision_conflict"),
    ({"end_date": "2020-01-02", "end_date_precision": "year"},
     "education_date_precision_conflict"),
    ({"end_date_precision": "private-invalid-precision"}, "invalid_review_item"),
])
def test_conflict_preserves_all_input_and_returns_only_safe_code(extra, code):
    payload = BASE | extra
    before = deepcopy(payload)
    with pytest.raises(ValidationAppError) as error:
        normalize_education_review(payload)
    assert error.value.code == code
    assert "private-" not in error.value.message
    assert payload == before


def test_new_review_display_alias_conflict_cannot_be_persisted():
    raw = {"institution_name": "Synthetic", "is_current": True, "end_date_display": "2020"}
    with pytest.raises(ValidationAppError) as error:
        ResumeReviewService._review_payload("education", raw)
    assert error.value.code == "current_claim_has_end_date"


def test_normalization_runs_final_validation(monkeypatch):
    import app.resumes.education_review as module

    original = module._validate
    seen = []

    def capture(payload):
        seen.append(dict(payload))
        return original(payload)

    monkeypatch.setattr(module, "_validate", capture)
    normalize_education_review(BASE | {"is_current": False, "end_date_display": "2020"})
    assert seen[0]["end_date"] is None
    assert seen[-1]["end_date"] == "2020-12-31"


@pytest.mark.asyncio
async def test_historical_review_conflict_is_visible_before_import_without_mutation():
    payload = BASE | {"is_current": True, "end_date": "2020-01-01"}
    item = SimpleNamespace(
        id=uuid4(), selected=True, claim_type="education", edited_payload=payload,
        import_action="create_new", duplicate_status="no_match", target_record_id=None,
        conflict_warnings=[],
    )

    class Session:
        async def scalars(self, _statement):
            return SimpleNamespace(all=lambda: [item])

    review = SimpleNamespace(id=uuid4(), user_id=uuid4(), version=1)
    plan = await ResumeReviewService(Session())._build_plan(review)
    assert not plan.ready
    assert plan.items[0].blockers == ["current_claim_has_end_date"]
    assert item.edited_payload == payload


@pytest.mark.asyncio
async def test_direct_import_defense_never_reaches_persistence():
    class Session:
        async def scalar(self, _statement):
            return None

        def add(self, _record):
            pytest.fail("contradictory Education reached persistence")

        async def flush(self):
            pytest.fail("contradictory Education reached flush")

    item = SimpleNamespace(
        id=uuid4(), claim_type="education", import_action="create_new",
        edited_payload=BASE | {"is_current": True, "end_date_display": "2020"},
    )
    with pytest.raises(ValidationAppError) as error:
        await ResumeReviewService(Session())._import_item(
            uuid4(), SimpleNamespace(), SimpleNamespace(), item, datetime.now(UTC),
        )
    assert error.value.code == "current_claim_has_end_date"


@pytest.fixture
async def education_owner():
    async with async_session_factory() as session:
        user = User(
            email=f"edu-current-{uuid4()}@example.invalid", full_name="Synthetic", role="user",
        )
        session.add(user)
        await session.commit()
        uid = user.id
    yield uid
    async with async_session_factory() as session:
        await session.execute(delete(User).where(User.id == uid))
        await session.commit()


async def create_review(session, uid, claim):
    doc = ResumeDocument(
        user_id=uid, storage_bucket="synthetic", storage_key=f"synthetic/{uuid4()}",
        original_filename="synthetic.pdf", normalized_filename="synthetic.pdf",
        content_type="application/pdf", file_size_bytes=128, checksum_sha256="a" * 64,
        upload_status="uploaded", processing_status="needs_review",
        consent_at=datetime.now(UTC), consent_version="test",
    )
    session.add(doc)
    await session.flush()
    job = ResumeProcessingJob(
        resume_document_id=doc.id, user_id=uid, status="needs_review",
        extraction_provider="synthetic", parsing_provider="synthetic",
        parser_schema_version="1", idempotency_key=str(uuid4()),
    )
    session.add(job)
    await session.flush()
    session.add(ResumeParsedResult(
        job_id=job.id, user_id=uid, schema_version="1",
        # These tests target date/import behavior, not uncertain review defaults.
        structured_result={"schema_version": "1", "education": [{"confidence": 0.95, **claim}]},
    ))
    await session.commit()
    return await ResumeReviewService(session).create(uid, doc.id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_catalogue_selection_survives_review_import(education_owner):
    from app.catalogues.institutions import CATALOGUE_VERSION, load_catalogue

    _, rows = load_catalogue()
    chosen = rows[0]
    uid = education_owner
    async with async_session_factory() as session:
        service = ResumeReviewService(session)
        review = await create_review(session, uid, {"institution_name": "Custom school"})
        item = review.items[0]
        assert item.edited_payload["institution_catalogue_id"] is None
        updated = await service.update_item(uid, review.id, item.id, ReviewItemUpdateRequest(
            expected_version=item.version,
            edited_payload={**item.edited_payload, "institution_name": chosen["name"],
                            "institution_catalogue_id": chosen["id"],
                            "institution_catalogue_version": CATALOGUE_VERSION},
        ))
        assert updated.edited_payload["institution_catalogue_id"] == chosen["id"]
        refreshed = await service._owned_review(uid, review.id)
        plan = await service.validate(uid, review.id, ReviewValidateRequest(
            expected_version=refreshed.version,
        ))
        assert plan.ready
        batch = await service.import_review(uid, review.id, ReviewImportRequest(
            expected_version=plan.version, idempotency_key=str(uuid4()), confirmed=True,
        ))
        assert batch.imported_count == 1
        row = await session.scalar(select(Education).where(Education.user_id == uid))
        assert row.institution_name == chosen["name"]
        assert row.institution_catalogue_id == chosen["id"]
        assert row.institution_catalogue_version == CATALOGUE_VERSION


@pytest.mark.integration
@pytest.mark.asyncio
async def test_candidate_catalogue_create_edit_and_old_client(education_owner):
    from datetime import date

    from app.catalogues.institutions import CATALOGUE_VERSION, load_catalogue
    from app.schemas.education import EducationCreateRequest, EducationUpdateRequest
    from app.services.education_service import EducationService

    _, rows = load_catalogue()
    async with async_session_factory() as session:
        service = EducationService(session)
        row = await service.create(education_owner, EducationCreateRequest(
            institution_name="Legacy manual school", degree="Synthetic degree",
            education_level="bachelors", start_date=date(2020, 1, 1),
        ))
        assert row.institution_catalogue_id is None
        for chosen in rows[:2]:
            row = await service.update(education_owner, row.id, EducationUpdateRequest(
                institution_name=chosen["name"], institution_catalogue_id=chosen["id"],
                institution_catalogue_version=CATALOGUE_VERSION,
            ))
            await session.refresh(row)
            assert row.institution_catalogue_id == chosen["id"]
            assert row.institution_name == chosen["name"]
        row = await service.update(education_owner, row.id, EducationUpdateRequest(grade="A"))
        assert row.institution_catalogue_id == rows[1]["id"]
        row = await service.update(education_owner, row.id, EducationUpdateRequest(
            institution_name="Legacy client custom edit",
        ))
        await session.refresh(row)
        assert row.institution_name == "Legacy client custom edit"
        assert row.institution_catalogue_id is None
        assert row.institution_catalogue_version is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_current_education_real_postgres_import_and_idempotency(education_owner):
    uid = education_owner
    async with async_session_factory() as session:
        service = ResumeReviewService(session)
        review = await create_review(session, uid, {
            "institution_name": "Synthetic", "is_current": True, "start_date_display": "2020",
        })
        plan = await service.validate(uid, review.id, ReviewValidateRequest(
            expected_version=review.version,
        ))
        assert plan.ready
        request = ReviewImportRequest(expected_version=plan.version,
                                      idempotency_key=str(uuid4()), confirmed=True)
        batch = await service.import_review(uid, review.id, request)
        assert batch.status == "completed" and batch.imported_count == 1
        assert (await service.import_review(uid, review.id, request)).id == batch.id
        rows = (await session.scalars(select(Education).where(Education.user_id == uid))).all()
        assert len(rows) == 1
        assert rows[0].is_currently_studying and rows[0].end_date is None
        assert rows[0].verification_status == "draft"


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("resolution", ["not_current", "clear_end"])
async def test_historical_conflict_requires_explicit_edit_and_preserves_payload(
    education_owner, resolution,
):
    uid = education_owner
    async with async_session_factory() as session:
        service = ResumeReviewService(session)
        review = await create_review(session, uid, {
            "institution_name": "Synthetic", "is_current": True,
        })
        item = await session.get(ResumeReviewItem, review.items[0].id)
        contradictory = dict(item.edited_payload, end_date="2020-12-31",
                             end_date_display="2020", end_date_precision="year")
        item.original_payload = item.edited_payload = contradictory
        await session.commit()  # Synthetic historical fixture only.
        plan = await service.validate(uid, review.id, ReviewValidateRequest(
            expected_version=review.version,
        ))
        assert not plan.ready and "current_claim_has_end_date" in plan.items[0].blockers
        with pytest.raises(ValidationAppError) as error:
            await service.import_review(uid, review.id, ReviewImportRequest(
                expected_version=plan.version, idempotency_key=str(uuid4()), confirmed=True,
            ))
        assert error.value.code == "review_not_importable"
        assert await session.scalar(select(func.count()).select_from(Education).where(
            Education.user_id == uid,
        )) == 0
        assert item.edited_payload == item.original_payload == contradictory
        corrected = (
            dict(contradictory, is_current=False) if resolution == "not_current"
            else dict(contradictory, end_date=None, end_date_display=None, end_date_precision=None)
        )
        await service.update_item(uid, review.id, item.id, ReviewItemUpdateRequest(
            expected_version=item.version, edited_payload=corrected,
        ))
        refreshed = await service.get(uid, review.id)
        valid = await service.validate(uid, review.id, ReviewValidateRequest(
            expected_version=refreshed.version,
        ))
        assert valid.ready
        batch = await service.import_review(uid, review.id, ReviewImportRequest(
            expected_version=valid.version, idempotency_key=str(uuid4()), confirmed=True,
        ))
        assert batch.imported_count == 1
        assert item.original_payload == contradictory


@pytest.mark.asyncio
async def test_explicit_skip_of_invalid_education_does_not_create_partial_failure():
    class Session:
        async def scalar(self, _statement):
            return None

    item = SimpleNamespace(
        id=uuid4(), claim_type="education", import_action="skip",
        edited_payload=BASE | {"is_current": True, "end_date_display": "2020"},
    )
    result = await ResumeReviewService(Session())._import_item(
        uuid4(), SimpleNamespace(), SimpleNamespace(), item, datetime.now(UTC),
    )
    assert result == ("skipped", None, None, [])
    assert item.review_status == "skipped"


@pytest.mark.asyncio
async def test_prior_success_keeps_provenance_idempotency_before_partial_recovery():
    prior = SimpleNamespace(record_type="education", record_id=uuid4())

    class Session:
        async def scalar(self, _statement):
            return prior

    item = SimpleNamespace(id=uuid4(), claim_type="education")
    result = await ResumeReviewService(Session())._import_item(
        uuid4(), SimpleNamespace(), SimpleNamespace(), item, datetime.now(UTC),
    )
    assert result == ("linked", "education", prior.record_id, ["already_imported"])
