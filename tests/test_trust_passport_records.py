from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.certification import CertificationCreateRequest
from app.schemas.education import EducationUpdateRequest
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
