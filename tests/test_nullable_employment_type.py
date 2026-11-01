"""Focused contract coverage for truthful nullable employment types."""

from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.employment.client_compatibility import (
    NULLABLE_EMPLOYMENT_TYPE_CAPABILITY,
    ClientMetadata,
    bind_client_metadata,
    reset_client_metadata,
)
from app.employment.enums import EmploymentType
from app.employment.type_normalization import normalize_employment_type
from app.models.employment import Employment
from app.organization_people.enums import OrganizationPersonRelationship
from app.resumes.review_schemas import EmploymentReviewClaim
from app.schemas.employer_verification import EmployerPortalEmployment
from app.schemas.employment import EmploymentPublic
from app.schemas.employment.requests import CreateEmploymentRequest, UpdateEmploymentRequest
from app.services.employment_service import EmploymentService
from app.services.organization_person_service import OrganizationPersonService
from app.services.resume_review_service import ResumeReviewService


@contextmanager
def capable_client():
    token = bind_client_metadata(
        ClientMetadata(capabilities=frozenset({NULLABLE_EMPLOYMENT_TYPE_CAPABILITY}))
    )
    try:
        yield
    finally:
        reset_client_metadata(token)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("full time", "full_time"),
        ("full-time", "full_time"),
        ("FULL_TIME", "full_time"),
        ("part time", "part_time"),
        ("Part-Time", "part_time"),
        ("contract", "contract"),
        ("contractor", "contract"),
        ("internship", "intern"),
        ("freelancer", "freelance"),
        ("other", "other"),
        (EmploymentType.GIG, "gig"),
        (None, None),
        ("", None),
        ("   ", None),
        ("seasonal", None),
        ("unsupported parser label", None),
    ],
)
def test_employment_type_normalization_preserves_only_recognized_values(
    source: EmploymentType | str | None,
    expected: str | None,
) -> None:
    assert normalize_employment_type(source) == expected


def test_employment_model_and_api_contract_are_nullable_without_a_default() -> None:
    column = Employment.__table__.c.employment_type
    assert column.nullable is True
    assert column.default is None
    assert CreateEmploymentRequest(
        subject_full_name="Synthetic Candidate",
        employer_legal_name="Synthetic Employer",
        job_title="Engineer",
        start_date=date(2024, 1, 1),
    ).employment_type is None
    assert (
        CreateEmploymentRequest(
            subject_full_name="Synthetic Candidate",
            employer_legal_name="Synthetic Employer",
            job_title="Engineer",
            employment_type=EmploymentType.CONTRACT,
            start_date=date(2024, 1, 1),
        ).employment_type
        is EmploymentType.CONTRACT
    )

    now = datetime.now(UTC)
    response = EmploymentPublic.model_validate(
        SimpleNamespace(
            id=uuid4(),
            subject_full_name="Synthetic Candidate",
            subject_email=None,
            employer_legal_name="Synthetic Employer",
            employer_trade_name=None,
            job_title="Engineer",
            employment_type=None,
            start_date=date(2024, 1, 1),
            end_date=None,
            work_location_city=None,
            work_location_country=None,
            work_location_region=None,
            work_arrangement=None,
            verification_method="document",
            verification_status="draft",
            submitted_at=None,
            reviewed_at=None,
            verified_at=None,
            assigned_reviewer_user_id=None,
            assigned_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    assert response.employment_type is None


def test_resume_review_accepts_null_and_openapi_declares_nullable_contract() -> None:
    from app.main import app

    assert EmploymentReviewClaim(
        claim_type="employment",
        company_name="Synthetic Employer",
        role_title="Engineer",
        employment_type=None,
    ).employment_type is None

    schemas = app.openapi()["components"]["schemas"]
    for schema_name in (
        "CreateEmploymentRequest",
        "UpdateEmploymentRequest",
        "EmploymentResponse",
        "EmployerPortalEmployment",
    ):
        options = schemas[schema_name]["properties"]["employment_type"]["anyOf"]
        assert {option.get("type") for option in options} >= {"null"}


@pytest.mark.asyncio
async def test_manual_create_without_type_persists_null() -> None:
    service = EmploymentService.__new__(EmploymentService)
    captured: list[Employment] = []

    class Repository:
        async def create(self, row: Employment) -> Employment:
            captured.append(row)
            row.id = uuid4()
            row.created_at = datetime.now(UTC)
            row.updated_at = row.created_at
            return row

    service._employment = Repository()
    service._settings = SimpleNamespace(enable_nullable_employment_type_writes=True)
    service._emit_audit = AsyncMock()
    service._users = SimpleNamespace(mark_employment_onboarding_completed_if_needed=AsyncMock())
    service._session = SimpleNamespace(commit=AsyncMock())

    with capable_client():
        response = await service.create(
            uuid4(),
            CreateEmploymentRequest(
                subject_full_name="Synthetic Candidate",
                employer_legal_name="Synthetic Employer",
                job_title="Engineer",
                start_date=date(2024, 1, 1),
            ),
        )

    assert captured[0].employment_type is None
    assert response.employment_type is None


def _employment(employment_type: str | None = "full_time") -> Employment:
    row = Employment(
        created_by_user_id=uuid4(),
        subject_full_name="Synthetic Candidate",
        subject_email="candidate@example.invalid",
        employer_legal_name="Synthetic Employer",
        job_title="Engineer",
        employment_type=employment_type,
        start_date=date(2024, 1, 1),
        verification_method="document",
        verification_status="draft",
    )
    row.id = uuid4()
    row.created_at = datetime.now(UTC)
    row.updated_at = row.created_at
    return row


def _update_service(row: Employment) -> EmploymentService:
    service = EmploymentService.__new__(EmploymentService)
    service._employment = SimpleNamespace(get_owned_active=AsyncMock(return_value=row))
    service._settings = SimpleNamespace(enable_nullable_employment_type_writes=True)
    service._verification_requests = SimpleNamespace(
        get_latest_for_subject_employment=AsyncMock(return_value=None),
        get_active_for_employment=AsyncMock(return_value=None),
    )
    service._verification_workflow = SimpleNamespace(record_action=AsyncMock())
    service._emit_audit = AsyncMock()
    service._session = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    return service


@pytest.mark.asyncio
async def test_update_distinguishes_omitted_type_from_explicit_null() -> None:
    row = _employment("contract")
    service = _update_service(row)

    with capable_client():
        await service.update(
            row.created_by_user_id,
            row.id,
            UpdateEmploymentRequest(job_title="Lead"),
        )
        assert row.employment_type == "contract"

        await service.update(
            row.created_by_user_id,
            row.id,
            UpdateEmploymentRequest(employment_type=None),
        )
        assert row.employment_type is None

        await service.update(
            row.created_by_user_id,
            row.id,
            UpdateEmploymentRequest(employment_type=EmploymentType.PART_TIME),
        )
        assert row.employment_type == "part_time"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Full-time", "full_time"),
        ("other", "other"),
        (None, None),
        ("seasonal", None),
    ],
)
async def test_resume_import_persists_normalized_or_null_type(
    source: str | None,
    expected: str | None,
) -> None:
    class Session:
        async def get(self, _model: object, _user_id: object) -> SimpleNamespace:
            return SimpleNamespace(
                full_name="Synthetic Candidate",
                email="candidate@example.invalid",
            )

    record = await ResumeReviewService(
        Session(),
        SimpleNamespace(enable_nullable_employment_type_writes=True),
    )._create_record(
        uuid4(),
        "employment",
        {
            "company_name": "Synthetic Employer",
            "role_title": "Engineer",
            "employment_type": source,
        },
    )

    assert record.employment_type == expected


def test_null_type_is_safe_for_employer_and_organization_projections() -> None:
    portal = EmployerPortalEmployment(
        employer_name="Synthetic Employer",
        job_title="Engineer",
        employment_type=None,
        country=None,
    )
    assert portal.employment_type is None

    relationship = OrganizationPersonService._infer_relationship_from_employment(
        OrganizationPersonService.__new__(OrganizationPersonService),
        _employment(None),
    )
    assert relationship is OrganizationPersonRelationship.EMPLOYEE


def test_migration_098_changes_nullability_and_has_documented_emergency_downgrade() -> None:
    path = Path(__file__).parents[1] / "alembic/versions/098_nullable_employment_type.py"
    spec = importlib.util.spec_from_file_location("migration_098", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = path.read_text()

    assert module.revision == "098"
    assert module.down_revision == "097"
    assert "nullable=True" in source
    assert "server_default=None" in source
    assert "WHERE employment_type IS NULL" in source
    assert "'other'::employment_type_enum" in source
    assert "nullable=False" in source
    assert "'full_time'::employment_type_enum" in source
