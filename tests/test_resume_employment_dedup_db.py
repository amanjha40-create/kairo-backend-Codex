import asyncio
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.db.session import async_session_factory
from app.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models.employment import Employment
from app.models.employment_document import EmploymentDocument
from app.models.resume_document import ResumeDocument
from app.models.resume_parsed_result import ResumeParsedResult
from app.models.resume_processing_job import ResumeProcessingJob
from app.models.user import User
from app.models.verification_request import VerificationRequest
from app.resumes.review_schemas import ReviewImportRequest, ReviewItemUpdateRequest
from app.services.resume_review_service import ResumeReviewService

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
CLAIM = {
    "company_name": "Synthetic Example Private Limited",
    "role_title": "Business Analyst",
    "start_date": "2021-01-01",
    "end_date": "2023-12-31",
    "is_current": False,
}


@pytest.fixture
async def owner():
    async with async_session_factory() as session:
        user = User(
            email=f"dedup-{uuid4()}@example.invalid",
            full_name="Synthetic Candidate",
            role="user",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        uid = user.id
    yield uid
    async with async_session_factory() as session:
        await session.execute(
            delete(VerificationRequest).where(VerificationRequest.subject_user_id == uid)
        )
        await session.execute(delete(Employment).where(Employment.created_by_user_id == uid))
        await session.execute(delete(User).where(User.id == uid))
        await session.commit()


async def career(uid, **changes):
    async with async_session_factory() as session:
        values = dict(
            created_by_user_id=uid,
            subject_full_name="Synthetic Candidate",
            employer_legal_name="Synthetic Example Pvt. Ltd.",
            job_title="Business Analyst",
            start_date=date(2021, 1, 1),
            end_date=date(2023, 12, 31),
            employment_type="full_time",
            verification_method="document",
            verification_status="verified",
            work_location_city="Existing City",
        )
        row = Employment(**(values | changes))
        session.add(row)
        await session.commit()
        return row.id


async def review(uid, claims):
    async with async_session_factory() as session:
        doc = ResumeDocument(
            user_id=uid,
            storage_bucket="synthetic",
            storage_key=f"synthetic/{uuid4()}",
            original_filename="synthetic.pdf",
            normalized_filename="synthetic.pdf",
            content_type="application/pdf",
            file_size_bytes=128,
            checksum_sha256="a" * 64,
            upload_status="uploaded",
            processing_status="needs_review",
            consent_at=datetime.now(UTC),
            consent_version="test",
        )
        session.add(doc)
        await session.flush()
        job = ResumeProcessingJob(
            resume_document_id=doc.id,
            user_id=uid,
            status="needs_review",
            extraction_provider="synthetic",
            parsing_provider="synthetic",
            parser_schema_version="1",
            idempotency_key=str(uuid4()),
        )
        session.add(job)
        await session.flush()
        session.add(
            ResumeParsedResult(
                job_id=job.id,
                user_id=uid,
                schema_version="1",
                structured_result={"schema_version": "1", "employments": claims},
            )
        )
        await session.commit()
        return await ResumeReviewService(session).create(uid, doc.id)


async def run_import(uid, item, key=None):
    async with async_session_factory() as session:
        return await ResumeReviewService(session).import_review(
            uid,
            item.id,
            ReviewImportRequest(
                expected_version=item.version,
                idempotency_key=key or str(uuid4()),
                confirmed=True,
            ),
        )


async def count(uid):
    async with async_session_factory() as session:
        return await session.scalar(
            select(func.count()).select_from(Employment).where(Employment.created_by_user_id == uid)
        )


async def test_existing_verified_plus_new_and_repeat_preserves_evidence(owner):
    original = await career(owner)
    async with async_session_factory() as session:
        evidence = EmploymentDocument(
            employment_id=original,
            uploaded_by_user_id=owner,
            document_type="offer_letter",
            object_key=f"synthetic/{uuid4()}",
            original_filename="synthetic.pdf",
            content_type="application/pdf",
            byte_size=1,
            checksum_sha256="b" * 64,
            verification_status="verified",
        )
        session.add(evidence)
        verification = VerificationRequest(
            origin_type="subject_initiated",
            subject_user_id=owner,
            employment_id=original,
            subject_name="Synthetic Candidate",
            subject_email="synthetic@example.invalid",
            request_type="employment",
            status="verified",
            requested_by_user_id=owner,
            claim_snapshot={"job_title": "Business Analyst"},
        )
        session.add(verification)
        await session.commit()
        evidence_id = evidence.id
        verification_id = verification.id
        verified_updated_at = verification.updated_at
    claims = [
        CLAIM | {"location": {"city": "Conflicting City"}},
        CLAIM | {"company_name": "Unrelated Company"},
    ]
    first = await review(owner, claims)
    result = await run_import(owner, first, "first-confirmation")
    assert (result.imported_count, result.linked_count, result.failed_count) == (1, 1, 0)
    assert await count(owner) == 2
    retry = await run_import(owner, first, "first-confirmation")
    assert retry.id == result.id
    second = await run_import(owner, await review(owner, claims))
    assert (second.imported_count, second.linked_count) == (0, 2)
    assert await count(owner) == 2
    async with async_session_factory() as session:
        existing = await session.get(Employment, original)
        assert (
            existing.employer_legal_name,
            existing.verification_status,
            existing.work_location_city,
        ) == ("Synthetic Example Pvt. Ltd.", "verified", "Existing City")
        assert (
            await session.get(EmploymentDocument, evidence_id)
        ).verification_status == "verified"
        retained = await session.get(VerificationRequest, verification_id)
        assert retained.status == "verified"
        assert retained.claim_snapshot == {"job_title": "Business Analyst"}
        assert retained.updated_at == verified_updated_at
        assert (
            await session.scalar(
                select(func.count())
                .select_from(VerificationRequest)
                .where(VerificationRequest.subject_user_id == owner)
            )
            == 1
        )


@pytest.mark.parametrize(
    "change",
    [
        {"role_title": "Senior Business Analyst"},
        {"role_title": "Software Engineer"},
        {"start_date": "2024-01-01", "end_date": "2025-01-01"},
    ],
)
async def test_distinct_roles_are_preserved(owner, change):
    await career(owner)
    result = await run_import(owner, await review(owner, [CLAIM | change]))
    assert result.imported_count == 1
    assert await count(owner) == 2


async def test_possible_match_defaults_to_skip_and_requires_explicit_distinct_confirmation(owner):
    await career(owner)
    ambiguous = CLAIM | {"start_date": None}
    first = await review(owner, [ambiguous])
    assert first.items[0].duplicate_status == "possible_match"
    assert (await run_import(owner, first)).skipped_count == 1
    assert await count(owner) == 1
    second = await review(owner, [ambiguous])
    async with async_session_factory() as session:
        svc = ResumeReviewService(session)
        item = second.items[0]
        await svc.update_item(
            owner,
            second.id,
            item.id,
            ReviewItemUpdateRequest(
                expected_version=item.version, selected=True, import_action="create_new"
            ),
        )
        second = await svc.get(owner, second.id)
        with pytest.raises(ValidationAppError):
            await svc.import_review(
                owner,
                second.id,
                ReviewImportRequest(
                    expected_version=second.version, idempotency_key="not-confirmed", confirmed=True
                ),
            )
        await session.rollback()
    async with async_session_factory() as session:
        svc = ResumeReviewService(session)
        second = await svc.get(owner, second.id)
        await svc.update_item(
            owner,
            second.id,
            second.items[0].id,
            ReviewItemUpdateRequest(
                expected_version=second.items[0].version,
                selected=True,
                import_action="create_new",
                confirm_distinct_role=True,
            ),
        )
        second = await svc.get(owner, second.id)
    assert (await run_import(owner, second)).imported_count == 1
    assert await count(owner) == 2
    # Identical imported payload/provenance avoids multiplication even with missing dates.
    assert (await run_import(owner, await review(owner, [ambiguous]))).linked_count == 1
    assert await count(owner) == 2


async def test_concurrent_different_reviews_and_repeated_rows_create_once(owner):
    left = await review(owner, [CLAIM, CLAIM])
    right = await review(owner, [CLAIM])
    results = await asyncio.gather(run_import(owner, left), run_import(owner, right))
    assert sum(result.imported_count for result in results) == 1
    assert sum(result.linked_count for result in results) == 2
    assert await count(owner) == 1


async def test_double_submit_same_key_returns_one_batch(owner):
    draft = await review(owner, [CLAIM])
    results = await asyncio.gather(
        run_import(owner, draft, "same-submit-key"), run_import(owner, draft, "same-submit-key")
    )
    assert results[0].id == results[1].id
    assert await count(owner) == 1
    with pytest.raises(ConflictError):
        await run_import(owner, draft, "different-retry-key")
    assert await count(owner) == 1


async def test_stale_preview_and_legacy_duplicates_are_safe(owner):
    draft = await review(owner, [CLAIM])
    ids = [await career(owner), await career(owner)]
    result = await run_import(owner, draft)
    assert result.linked_count == 1 and result.imported_count == 0
    assert result.results[0].record_id in ids
    assert await count(owner) == 2


async def test_legacy_create_override_cannot_duplicate_exact_or_update_verified(owner):
    await career(owner)
    draft = await review(owner, [CLAIM])
    async with async_session_factory() as session:
        svc = ResumeReviewService(session)
        item = draft.items[0]
        with pytest.raises(ValidationAppError):
            await svc.update_item(
                owner,
                draft.id,
                item.id,
                ReviewItemUpdateRequest(
                    expected_version=item.version, import_action="update_existing"
                ),
            )
        await session.rollback()
        item = await svc.update_item(
            owner,
            draft.id,
            item.id,
            ReviewItemUpdateRequest(
                expected_version=item.version,
                import_action="create_new",
                confirm_distinct_role=True,
            ),
        )
        assert item.import_action == "link_existing"
        draft = await svc.get(owner, draft.id)
    assert (await run_import(owner, draft)).linked_count == 1
    assert await count(owner) == 1


async def test_foreign_review_fails_closed(owner):
    draft = await review(owner, [CLAIM])
    with pytest.raises(NotFoundError):
        await run_import(uuid4(), draft)
    assert await count(owner) == 0


async def test_changed_candidate_invalidates_distinct_role_confirmation(owner):
    original = await career(owner)
    draft = await review(owner, [CLAIM | {"start_date": None}])
    async with async_session_factory() as session:
        svc = ResumeReviewService(session)
        item = draft.items[0]
        await svc.update_item(
            owner,
            draft.id,
            item.id,
            ReviewItemUpdateRequest(
                expected_version=item.version,
                selected=True,
                import_action="create_new",
                confirm_distinct_role=True,
            ),
        )
        draft = await svc.get(owner, draft.id)
        existing = await session.get(Employment, original)
        existing.start_date = date(2020, 1, 1)
        await session.commit()
    with pytest.raises(ValidationAppError):
        await run_import(owner, draft)
    assert await count(owner) == 1


async def test_stale_exact_link_does_not_link_to_a_changed_role(owner):
    original = await career(owner)
    draft = await review(owner, [CLAIM])
    assert draft.items[0].import_action == "link_existing"
    async with async_session_factory() as session:
        existing = await session.get(Employment, original)
        existing.job_title = "Software Engineer"
        await session.commit()
    result = await run_import(owner, draft)
    assert result.imported_count == 1 and result.linked_count == 0
    assert await count(owner) == 2


async def test_other_accounts_employment_is_not_a_match(owner):
    async with async_session_factory() as session:
        other = User(
            email=f"dedup-other-{uuid4()}@example.invalid",
            full_name="Other Synthetic",
            role="user",
            is_active=True,
        )
        session.add(other)
        await session.commit()
        other_id = other.id
    try:
        await career(other_id)
        result = await run_import(owner, await review(owner, [CLAIM]))
        assert result.imported_count == 1 and result.linked_count == 0
        assert await count(owner) == 1
        assert await count(other_id) == 1
    finally:
        async with async_session_factory() as session:
            await session.execute(
                delete(Employment).where(Employment.created_by_user_id == other_id)
            )
            await session.execute(delete(User).where(User.id == other_id))
            await session.commit()
