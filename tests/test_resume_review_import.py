from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.resumes.normalization import (
    date_ranges_overlap,
    normalize_date,
    normalize_review_date,
    normalize_text,
    normalize_url,
    payload_hash,
    stable_claim_id,
)
from app.resumes.review_schemas import (
    EmploymentReviewClaim,
    ReviewImportRequest,
    ReviewItemUpdateRequest,
    review_claim_adapter,
)
from app.services.resume_duplicate_service import ResumeDuplicateService, classify_match
from app.services.resume_review_service import ResumeReviewService


def test_stable_claim_ids_and_payload_hashes_are_deterministic() -> None:
    parsed_id = uuid4()
    payload = {"claim_type": "skill", "name": "Python"}
    assert stable_claim_id(parsed_id, "skill", 0, payload) == stable_claim_id(parsed_id, "skill", 0, payload)
    assert stable_claim_id(parsed_id, "skill", 0, payload) != stable_claim_id(parsed_id, "skill", 1, payload)
    assert payload_hash({"b": 2, "a": 1}) == payload_hash({"a": 1, "b": 2})


def test_normalization_is_deterministic_and_unicode_safe() -> None:
    assert normalize_text("  ACME—Labs  ") == "acme labs"
    assert normalize_url("HTTPS://Example.COM/work/") == "https://example.com/work"
    assert normalize_url("javascript:alert(1)") == ""
    assert date_ranges_overlap(date(2020, 1, 1), date(2021, 1, 1), date(2020, 6, 1), None)
    assert date_ranges_overlap("2020-01-01", "2021-01-01", date(2020, 6, 1), None)
    assert normalize_date("not-a-date") is None


def test_duplicate_classification_is_deterministic() -> None:
    assert classify_match(primary_equal=True, secondary_equal=True, exact_dates=True, ranges_overlap=True, url_equal=False)[0] == "exact_match"
    assert classify_match(primary_equal=True, secondary_equal=False, exact_dates=False, ranges_overlap=True, url_equal=False)[0] == "probable_match"
    assert classify_match(primary_equal=True, secondary_equal=False, exact_dates=False, ranges_overlap=False, url_equal=False)[0] == "possible_match"
    assert classify_match(primary_equal=False, secondary_equal=False, exact_dates=False, ranges_overlap=False, url_equal=False)[0] is None


@pytest.mark.asyncio
async def test_skill_duplicate_matching_links_existing_normalized_name() -> None:
    existing_id = uuid4()

    class FakeSession:
        async def scalars(self, _statement: object) -> SimpleNamespace:
            return SimpleNamespace(all=lambda: [SimpleNamespace(id=existing_id, name="Financial Research & Valuation")])

    result = await ResumeDuplicateService(FakeSession()).assess(
        uuid4(), "skill", {"name": " financial research & valuation "},
    )
    assert result.status == "exact_match"
    assert result.candidates[0]["record_id"] == str(existing_id)


def test_review_claims_reject_unknown_and_verification_fields() -> None:
    with pytest.raises(ValidationError):
        review_claim_adapter.validate_python({
            "claim_type": "employment",
            "company_name": "Synthetic Company",
            "verified": True,
        })
    with pytest.raises(ValidationError):
        review_claim_adapter.validate_python({"claim_type": "employment", "company_name": "A", "end_date": "2022-01-01", "start_date": "2023-01-01"})


def test_review_claim_does_not_accept_candidate_email_or_phone() -> None:
    with pytest.raises(ValidationError):
        review_claim_adapter.validate_python({"claim_type": "profile", "full_name": "Synthetic", "email": "example@example.invalid"})
    with pytest.raises(ValidationError):
        review_claim_adapter.validate_python({"claim_type": "profile", "phone": "+10000000000"})


def test_import_confirmation_and_idempotency_key_are_mandatory() -> None:
    with pytest.raises(ValidationError):
        ReviewImportRequest(expected_version=1, idempotency_key="short", confirmed=True)
    with pytest.raises(ValidationError):
        ReviewImportRequest(expected_version=1, idempotency_key="candidate-confirmation", confirmed=False)


def test_item_update_rejects_extra_mutation_controls() -> None:
    with pytest.raises(ValidationError):
        ReviewItemUpdateRequest(expected_version=1, selected=True, verification_status="verified")


def test_import_plan_only_blocks_structurally_unusable_employment_claims() -> None:
    service = ResumeReviewService(SimpleNamespace())
    assert "unsupported_import_target" not in service._required_blockers("project", {"title": "Synthetic"})
    assert service._required_blockers("employment", {}) == ["missing_employment_identity"]
    assert service._required_blockers("employment", {"company_name": "Synthetic"}) == []
    assert service._required_blockers("employment", {
        "company_name": "Synthetic", "role_title": "Engineer", "start_date": "2024-01-01",
    }) == []
    assert service._action_blockers(
        "link_existing",
        "education",
        {"institution_name": "Synthetic", "degree": "Synthetic"},
    ) == []


@pytest.mark.asyncio
async def test_excluded_or_review_only_claims_do_not_block_import() -> None:
    review = SimpleNamespace(id=uuid4(), user_id=uuid4(), version=1)
    item = SimpleNamespace(
        id=uuid4(),
        selected=True,
        import_action="skip",
        claim_type="other",
        edited_payload={"claim_type": "other"},
        duplicate_status="no_match",
        target_record_id=None,
        conflict_warnings=[],
    )

    class FakeSession:
        async def scalars(self, _statement: object) -> SimpleNamespace:
            return SimpleNamespace(all=lambda: [item])

    plan = await ResumeReviewService(FakeSession())._build_plan(review)

    assert plan.ready is True
    assert plan.items[0].action == "skip"
    assert plan.items[0].blockers == []


def test_incomplete_resume_claims_remain_importable_for_career_completion() -> None:
    service = ResumeReviewService(SimpleNamespace())
    assert service._required_blockers("education", {
        "institution_name": "Synthetic Institute", "degree": "Synthetic Degree",
    }) == []
    assert service._required_blockers("certification", {
        "title": "Synthetic Certificate",
    }) == []
    assert service._completion_warnings("certification", {
        "title": "Synthetic Certificate", "issuing_organization": None, "issued_date": None,
    }) == ["needs_completion_in_career", "missing_issued_date"]
    assert service._required_blockers("certification", {"title": "Synthetic Certificate"}) == []
    assert service._completion_warnings("education", {
        "institution_name": "Synthetic Institute", "degree": "Synthetic Degree",
        "education_level": None, "start_date": None,
    }) == ["needs_completion_in_career", "missing_start_date", "missing_end_date", "education_level"]


def test_incomplete_employment_is_importable_and_marked_for_career_completion() -> None:
    service = ResumeReviewService(SimpleNamespace())
    assert service._required_blockers("employment", {"company_name": "Synthetic", "role_title": "Engineer"}) == []
    assert service._completion_warnings("employment", {
        "company_name": "Synthetic", "role_title": "Engineer", "start_date": None,
        "end_date": None, "is_current": False,
    }) == ["needs_completion_in_career", "missing_start_date", "missing_end_date"]


def test_current_employment_with_missing_end_date_is_not_incomplete() -> None:
    service = ResumeReviewService(SimpleNamespace())
    assert service._completion_warnings("employment", {
        "company_name": "Synthetic", "role_title": "Engineer", "start_date": None,
        "end_date": None, "is_current": True,
    }) == ["needs_completion_in_career", "missing_start_date"]


def test_projects_and_skills_are_importable_when_their_identity_is_present() -> None:
    service = ResumeReviewService(SimpleNamespace())
    assert service._required_blockers("project", {"title": "Synthetic project"}) == []
    assert service._required_blockers("skill", {"name": "Synthetic skill"}) == []


@pytest.mark.asyncio
async def test_education_import_preserves_missing_optional_metadata() -> None:
    service = ResumeReviewService(SimpleNamespace())
    record = await service._create_record(uuid4(), "education", {
        "institution_name": "Synthetic Institute",
        "degree": "Bachelor of Business Administration",
        "education_level": None,
        "start_date": None,
    })
    assert record.institution_name == "Synthetic Institute"
    assert record.degree == "Bachelor of Business Administration"
    assert record.education_level is None
    assert record.start_date is None


def test_import_plan_accepts_nullable_employment_location() -> None:
    service = ResumeReviewService(SimpleNamespace())

    assert service._ignored_fields(
        "employment",
        {"company_name": "Synthetic Company", "location": None},
    ) == []


@pytest.mark.parametrize(
    ("value", "display", "is_end", "expected"),
    [
        (None, "Apr 2023", False, ("2023-04-01", "month")),
        (None, "Jan 2025", True, ("2025-01-31", "month")),
        ("2023", None, False, ("2023-01-01", "year")),
        ("2025", None, True, ("2025-12-31", "year")),
        ("Present", None, True, (None, None)),
    ],
)
def test_resume_review_date_normalization(value, display, is_end, expected) -> None:
    assert normalize_review_date(value, display, is_end=is_end) == expected


def test_edited_employment_dates_are_normalized_before_review_validation() -> None:
    payload = ResumeReviewService._normalize_review_payload("employment", {
        "claim_type": "employment", "company_name": "Synthetic", "role_title": "Engineer",
        "start_date": None, "start_date_display": "Apr 2023", "end_date": None,
        "end_date_display": "Jan 2025", "is_current": False,
    })
    assert payload["start_date"] == "2023-04-01"
    assert payload["end_date"] == "2025-01-31"
    assert payload["start_date_precision"] == "month"
    assert payload["end_date_precision"] == "month"


def test_edited_education_dates_preserve_month_and_year_precision() -> None:
    payload = ResumeReviewService._normalize_review_payload("education", {
        "claim_type": "education", "institution_name": "Synthetic University", "degree": "Synthetic Degree",
        "start_date": None, "start_date_display": "Apr 2023", "end_date": "2025",
    })

    assert payload["start_date"] == "2023-04-01"
    assert payload["start_date_precision"] == "month"
    assert payload["end_date"] == "2025-12-31"
    assert payload["end_date_precision"] == "year"


@pytest.mark.asyncio
async def test_education_import_persists_date_precision() -> None:
    service = ResumeReviewService(SimpleNamespace())
    record = await service._create_record(uuid4(), "education", {
        "institution_name": "Synthetic Institute",
        "degree": "Synthetic Degree",
        "start_date": date(2023, 4, 1),
        "start_date_precision": "month",
        "end_date": date(2025, 1, 31),
        "end_date_precision": "month",
    })

    assert record.start_date_precision == "month"
    assert record.end_date_precision == "month"


def test_resume_import_does_not_require_location_but_normal_career_contract_still_validates_country() -> None:
    from app.schemas.employment.requests import CreateEmploymentRequest

    assert ResumeReviewService._required_blockers("employment", {
        "company_name": "Synthetic", "role_title": "Engineer", "start_date": "2024-01-01", "location": None,
    }) == []
    assert CreateEmploymentRequest(
        subject_full_name="Synthetic Candidate", employer_legal_name="Synthetic", job_title="Engineer",
        start_date="2024-01-01", work_location_country="IN",
    ).work_location_country == "IN"
    with pytest.raises(ValidationError):
        CreateEmploymentRequest(
            subject_full_name="Synthetic Candidate", employer_legal_name="Synthetic", job_title="Engineer",
            start_date="2024-01-01", work_location_country="India",
        )


@pytest.mark.asyncio
async def test_employment_duplicate_protection_treats_verified_records_as_protected() -> None:
    existing_id = uuid4()

    class FakeSession:
        def __init__(self) -> None:
            self.calls = 0

        async def scalars(self, _statement: object) -> SimpleNamespace:
            self.calls += 1
            if self.calls == 2:
                return SimpleNamespace(all=lambda: [])
            return SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(
                        id=existing_id,
                        employer_legal_name="Example Corp",
                        job_title="Engineer",
                        start_date=date(2020, 1, 1),
                        end_date=date(2021, 1, 1),
                        verification_status="verified",
                        verified_at=None,
                    )
                ]
            )

    result = await ResumeDuplicateService(FakeSession()).assess(
        uuid4(),
        "employment",
        {
            "company_name": "Example Corp",
            "role_title": "Engineer",
            "start_date": date(2020, 1, 1),
            "end_date": date(2021, 1, 1),
        },
    )

    assert result.status == "exact_match"
    assert result.candidates[0]["protected"] is True


def test_review_payload_bounds_profile_headline_to_canonical_user_limit() -> None:
    payload = ResumeReviewService._review_payload(
        "profile",
        {"professional_headline": "A" * 300},
    )

    assert len(payload["professional_headline"]) == 255


def test_review_payload_normalizes_parser_work_arrangement_case() -> None:
    payload = ResumeReviewService._review_payload(
        "employment",
        {
            "company_name": "Synthetic Company",
            "role_title": "Engineer",
            "work_arrangement": "Remote",
        },
    )

    assert payload["work_arrangement"] == "remote"


def test_review_accepts_extracted_country_name_for_candidate_correction() -> None:
    claim = review_claim_adapter.validate_python({
        "claim_type": "employment",
        "company_name": "Synthetic Company",
        "role_title": "Engineer",
        "start_date": "2024-01-01",
        "location": {"country": "India"},
    })

    assert claim.location is not None
    assert claim.location.country == "India"


def test_review_preserves_unknown_current_status() -> None:
    claim = review_claim_adapter.validate_python({
        "claim_type": "education",
        "institution_name": "Synthetic Institute",
        "degree": "Synthetic Degree",
        "is_current": None,
    })

    assert claim.is_current is None


def test_review_requires_canonical_education_level() -> None:
    with pytest.raises(ValidationError):
        review_claim_adapter.validate_python({
            "claim_type": "education",
            "institution_name": "Synthetic Institute",
            "degree": "Synthetic Degree",
            "education_level": "bachelor",
        })

    claim = review_claim_adapter.validate_python({
        "claim_type": "education",
        "institution_name": "Synthetic Institute",
        "degree": "Synthetic Degree",
        "education_level": "bachelors",
    })
    assert claim.education_level == "bachelors"


def test_verified_or_active_records_are_protected() -> None:
    assert ResumeReviewService._protected(SimpleNamespace(verification_status="verified", verified_at=None))
    assert ResumeReviewService._protected(SimpleNamespace(verification_status="pending", verified_at=object()))
    assert not ResumeReviewService._protected(SimpleNamespace(verification_status="draft", verified_at=None))


def test_employment_schema_preserves_candidate_provided_unverified_fields_only() -> None:
    claim = EmploymentReviewClaim(
        claim_type="employment",
        company_name="Synthetic Company",
        role_title="Engineer",
        start_date=date(2024, 1, 1),
        is_current=True,
        location={"country": "IN"},
    )
    assert claim.company_name == "Synthetic Company"
    assert not hasattr(claim, "verification_status")


def test_openapi_documents_resume_review_contracts() -> None:
    from app.main import app

    paths = app.openapi()["paths"]
    assert "/api/v1/resumes/{resume_id}/review-session" in paths
    assert "/api/v1/resume-reviews/{review_id}/items/{item_id}" in paths
    assert "/api/v1/resume-reviews/{review_id}/validate" in paths
    assert "/api/v1/resume-reviews/{review_id}/import" in paths
    assert "/api/v1/resume-reviews/{review_id}/import-status" in paths


@pytest.mark.asyncio
@pytest.mark.integration
async def test_confirmed_resume_claim_import_is_idempotent_and_unverified() -> None:
    from sqlalchemy import delete, select

    from app.db.session import async_session_factory
    from app.models.employment import Employment
    from app.models.resume_document import ResumeDocument
    from app.models.resume_parsed_result import ResumeParsedResult
    from app.models.resume_processing_job import ResumeProcessingJob
    from app.models.resume_record_provenance import ResumeRecordProvenance
    from app.models.user import User
    from app.models.verification_request import VerificationRequest
    from app.resumes.review_schemas import ReviewImportRequest, ReviewValidateRequest

    now = datetime.now(UTC)
    user_id = resume_id = employment_id = existing_employment_id = None
    async with async_session_factory() as session:
        user = User(email=f"resume-import-{uuid4()}@example.invalid", full_name="Synthetic Candidate", role="user", is_active=True)
        session.add(user)
        await session.flush()
        user_id = user.id
        existing_employment = Employment(
            created_by_user_id=user.id,
            subject_full_name=user.full_name,
            subject_email=user.email,
            employer_legal_name="Unrelated Existing Company",
            job_title="Analyst",
            employment_type="full_time",
            start_date=date(2022, 1, 1),
            work_location_country="IN",
            verification_method="document",
            verification_status="draft",
        )
        session.add(existing_employment)
        await session.flush()
        existing_employment_id = existing_employment.id
        document = ResumeDocument(
            user_id=user.id,
            storage_bucket="synthetic-private-bucket",
            storage_key=f"resumes/{user.id}/{uuid4()}/resume.pdf",
            original_filename="synthetic.pdf",
            normalized_filename="synthetic.pdf",
            content_type="application/pdf",
            file_size_bytes=128,
            checksum_sha256="a" * 64,
            upload_status="uploaded",
            processing_status="needs_review",
            consent_at=now,
            consent_version="test-v1",
        )
        session.add(document)
        await session.flush()
        resume_id = document.id
        job = ResumeProcessingJob(
            resume_document_id=document.id,
            user_id=user.id,
            status="needs_review",
            extraction_provider="synthetic",
            parsing_provider="synthetic",
            parser_schema_version="1",
            idempotency_key="synthetic-processing-job",
        )
        session.add(job)
        await session.flush()
        session.add(ResumeParsedResult(
            job_id=job.id,
            user_id=user.id,
            schema_version="1",
            structured_result={
                "schema_version": "1",
                "employments": [{
                    "company_name": "Synthetic Company",
                    "role_title": "Engineer",
                    "employment_type": "full_time",
                    "start_date": "2024-01-01",
                    "is_current": True,
                    "location": {"country": "IN"},
                }],
                "education": [{
                    "institution_name": "Synthetic University",
                    "degree": "Synthetic Degree",
                }],
            },
            parser_metadata={},
            warnings=[],
        ))
        await session.commit()

        service = ResumeReviewService(session)
        review = await service.create(user.id, document.id)
        assert review.status == "draft"
        assert len(review.items) == 2
        plan = await service.validate(user.id, review.id, ReviewValidateRequest(expected_version=review.version))
        assert plan.ready
        assert [item.claim_type for item in plan.items] == ["employment"]
        request = ReviewImportRequest(expected_version=plan.version, idempotency_key="synthetic-confirmed-import", confirmed=True)
        first = await service.import_review(user.id, review.id, request)
        second = await service.import_review(user.id, review.id, request)
        assert first.id == second.id
        assert first.status == "completed"
        assert first.imported_count == 1
        employment_id = first.results[0].record_id
        employment = await session.get(Employment, employment_id)
        assert employment.verification_status == "draft"
        duplicate = await ResumeDuplicateService(session).assess(user.id, "employment", {
            "claim_type": "employment",
            "company_name": "Synthetic Company",
            "role_title": "Engineer",
            "employment_type": "full_time",
            "start_date": "2024-01-01",
            "end_date": None,
            "is_current": True,
            "location": {"country": "IN"},
        })
        assert duplicate.status == "exact_match"
        assert duplicate.candidates[0]["record_id"] == str(employment_id)
        assert await session.scalar(select(ResumeRecordProvenance).where(ResumeRecordProvenance.record_id == employment_id))
        assert await session.scalar(select(VerificationRequest).where(VerificationRequest.employment_id == employment_id)) is None

    async with async_session_factory() as cleanup:
        if resume_id:
            await cleanup.execute(delete(ResumeDocument).where(ResumeDocument.id == resume_id))
        if employment_id or existing_employment_id:
            await cleanup.execute(delete(Employment).where(Employment.id.in_(
                [value for value in (employment_id, existing_employment_id) if value]
            )))
        if user_id:
            await cleanup.execute(delete(User).where(User.id == user_id))
        await cleanup.commit()
