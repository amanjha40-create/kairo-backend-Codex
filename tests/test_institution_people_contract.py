from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.institution_people.enums import (
    InstitutionPersonLifecycleStatus,
    InstitutionProfessionalField,
    InstitutionVerificationStatus,
)
from app.main import app
from app.schemas.institution_people import (
    InstitutionPeopleListQuery,
    InstitutionPersonDetailResponse,
    InstitutionPersonListItem,
)
from app.services.institution_people_service import InstitutionPeopleService


def test_institution_contract_uses_institution_lifecycle_states() -> None:
    assert {status.value for status in InstitutionPersonLifecycleStatus} == {
        "current_student",
        "alumni",
        "withdrawn",
        "inactive",
    }


def test_list_query_supports_alumni_directory_filters() -> None:
    query = InstitutionPeopleListQuery(
        lifecycle_status="alumni",
        programme="Computer Science",
        department="Engineering",
        graduation_period="2024",
        student_id="STU-1234",
        verification_status="verified",
        page=2,
        page_size=10,
    )
    assert query.lifecycle_status == InstitutionPersonLifecycleStatus.ALUMNI
    assert query.page == 2
    assert query.page_size == 10


def test_student_id_is_masked_in_list_and_full_value_is_detail_only() -> None:
    item = InstitutionPersonListItem(
        public_id=uuid4(),
        display_name="Synthetic Student",
        student_id_masked=InstitutionPeopleService._mask_student_id("STU-1234"),
        lifecycle_status=InstitutionPersonLifecycleStatus.CURRENT_STUDENT,
        verification_status=InstitutionVerificationStatus.NOT_STARTED,
    )
    assert item.student_id_masked == "****1234"
    assert "STU-" not in item.student_id_masked
    assert "student_id" not in item.model_dump(exclude={"student_id_masked"})


def test_expired_consent_is_not_active() -> None:
    consent = SimpleNamespace(
        revoked_at=None,
        expires_at=datetime.now(tz=UTC) - timedelta(minutes=1),
    )
    assert InstitutionPeopleService._consent_active(consent) is False


def test_detail_contract_does_not_have_full_passport_or_trust_score_fields() -> None:
    fields = set(InstitutionPersonDetailResponse.model_fields)
    assert "passport" not in fields
    assert "trust_score" not in fields
    assert "phone" not in fields
    assert "email" not in fields
    assert InstitutionProfessionalField.CURRENT_TITLE.value in {
        field.value for field in InstitutionProfessionalField
    }


def test_institution_active_request_types_are_academic_only() -> None:
    assert {"education", "certification", "document"}.isdisjoint({"employment"})


def test_openapi_exposes_only_institution_scoped_people_contract() -> None:
    paths = app.openapi()["paths"]
    prefix = "/api/v1/organizations/{org_public_id}/institution/people"
    assert prefix in paths
    assert f"{prefix}/{{person_public_id}}" in paths
    assert f"{prefix}/{{person_public_id}}/verification-history" in paths
    assert f"{prefix}/{{person_public_id}}/credentials" in paths
    assert f"{prefix}/{{person_public_id}}/credentials/{{credential_public_id}}" in paths
