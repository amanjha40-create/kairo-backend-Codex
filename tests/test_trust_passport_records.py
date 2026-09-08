from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.certification import CertificationCreateRequest
from app.schemas.education import EducationResponse, EducationUpdateRequest
from app.schemas.project import ProjectCreateRequest
from app.schemas.skill import SkillCreateRequest


def test_skill_names_are_trimmed_and_duplicate_key_is_case_insensitive() -> None:
    item = SkillCreateRequest(name="  Financial  Modeling ")
    assert item.name == "Financial Modeling"
    assert item.name.casefold() == "financial modeling"


def test_project_dates_and_current_state_are_validated() -> None:
    with pytest.raises(ValidationError):
        ProjectCreateRequest(title="Launch", start_date=date(2024, 2, 1), end_date=date(2024, 1, 1))
    with pytest.raises(ValidationError):
        ProjectCreateRequest(title="Launch", is_ongoing=True, end_date=date(2024, 1, 1))


def test_education_partial_update_rejects_invalid_date_order() -> None:
    with pytest.raises(ValidationError):
        EducationUpdateRequest(start_date=date(2024, 5, 1), end_date=date(2024, 4, 1))


def test_career_education_response_preserves_year_only_import_bounds() -> None:
    now = datetime.now(UTC)
    response = EducationResponse(
        id=uuid4(),
        user_id=uuid4(),
        institution_name="Synthetic State University",
        degree="BSc Computer Science",
        education_level=None,
        start_date=date(2015, 1, 1),
        start_date_precision="year",
        end_date=date(2019, 12, 31),
        end_date_precision="year",
        is_currently_studying=False,
        verification_status="draft",
        created_at=now,
        updated_at=now,
    )

    payload = response.model_dump(mode="json")
    assert payload["start_date"] == "2015-01-01"
    assert payload["start_date_precision"] == "year"
    assert payload["end_date"] == "2019-12-31"
    assert payload["end_date_precision"] == "year"
    assert payload["is_currently_studying"] is False


def test_certification_expiry_and_urls_are_validated() -> None:
    with pytest.raises(ValidationError):
        CertificationCreateRequest(
            title="AWS", issuing_organization="Amazon", issued_date=date(2024, 2, 1),
            expiry_date=date(2024, 1, 1),
        )
    with pytest.raises(ValidationError):
        CertificationCreateRequest(
            title="AWS", issuing_organization="Amazon", issued_date=date(2024, 1, 1),
            credential_url="javascript:alert(1)",
        )
    assert str(CertificationCreateRequest(
        title="AWS", issuing_organization="Amazon", issued_date=date(2024, 1, 1),
        credential_url="credly.com/credentials/synthetic",
    ).credential_url) == "https://credly.com/credentials/synthetic"
