from uuid import uuid4

import pytest

from app.catalogues.education_identity import FIELDS, education_identity
from app.catalogues.institutions import CATALOGUE_VERSION, load_catalogue
from app.exceptions import ValidationAppError
from app.models.education import Education
from app.resumes.education_review import normalize_education_review
from app.schemas.education import EducationUpdateRequest
from app.services.resume_review_service import ResumeReviewService


def selection(index=0):
    _, rows = load_catalogue()
    return dict(
        institution_name=rows[index]["name"],
        institution_catalogue_id=rows[index]["id"],
        institution_catalogue_version=CATALOGUE_VERSION,
    )


def test_manual_and_legacy_names_remain_unlinked():
    result = education_identity({"institution_name": "Custom institution"})
    assert result["institution_name"] == "Custom institution"
    assert all(result[field] is None for field in FIELDS)


def test_selection_and_reselection():
    assert education_identity(selection()) == selection()
    assert education_identity(selection(1), selection()) == selection(1)


@pytest.mark.parametrize("echo", [False, True])
def test_manual_edit_clears_selection(echo):
    payload = selection() if echo else {}
    payload["institution_name"] = "My custom value"
    result = education_identity(payload, selection())
    assert result["institution_name"] == "My custom value"
    assert all(result[field] is None for field in FIELDS)


def test_unrelated_legacy_patch_preserves_selection():
    patch = EducationUpdateRequest(degree="New degree").model_dump(exclude_unset=True)
    assert education_identity(patch, selection()) == patch


@pytest.mark.parametrize(
    "field,value",
    [
        ("institution_catalogue_id", "unknown"),
        ("institution_catalogue_version", "unknown"),
        ("institution_name", "Different name"),
        ("institution_catalogue_version", None),
    ],
)
def test_invalid_explicit_selection_rejected(field, value):
    payload = {**selection(), field: value}
    with pytest.raises(ValidationAppError):
        education_identity(payload)


def test_parser_never_attaches_catalogue_identity():
    result = ResumeReviewService._review_payload("education", selection())
    assert all(result[field] is None for field in FIELDS)


@pytest.mark.asyncio
@pytest.mark.parametrize("linked", [True, False])
async def test_review_and_admin_shared_create_preserves_identity(linked):
    payload = selection() if linked else {"institution_name": "Custom school"}
    draft = normalize_education_review({"claim_type": "education", **payload})
    record = await ResumeReviewService(None)._create_record(uuid4(), "education", draft)
    assert record.institution_name == payload["institution_name"]
    for field in FIELDS:
        assert getattr(record, field) == payload.get(field)


def test_admin_shared_update_clears_identity_without_changing_verification():
    record = Education(**selection(), verification_status="draft")
    ResumeReviewService(None)._apply_update(record, "education", {"institution_name": "Manual"})
    assert record.institution_name == "Manual"
    assert record.institution_catalogue_id is None
    assert record.institution_catalogue_version is None
    assert record.verification_status == "draft"
