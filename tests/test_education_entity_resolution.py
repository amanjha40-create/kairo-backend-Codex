"""Deterministic, provider-neutral Education resolution policy."""

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.education.entity_resolution import (
    canonical_board,
    canonical_education_level,
    resolve_education_entity,
)


def education(
    degree: str,
    *,
    institution: str = "Synthetic School",
    year: int | None = 2020,
):
    return SimpleNamespace(
        id=uuid4(),
        institution_name=institution,
        degree=degree,
        field_of_study=None,
        education_level="high_school",
        end_date=date(year, 12, 31) if year else None,
    )


@pytest.mark.parametrize(
    "left,right,canonical",
    [
        ("Class X", "High School", "class_x"),
        ("Class X", "Matriculation", "class_x"),
        ("Class 10", "SSC", "class_x"),
        ("Class XII", "HSC", "class_xii"),
    ],
)
def test_school_level_aliases_are_semantic_and_deterministic(left, right, canonical):
    assert canonical_education_level(left) == canonical
    assert canonical_education_level(right) == canonical


def test_board_aliases_only_cover_approved_equivalence():
    assert canonical_board("CBSE") == canonical_board("Central Board of Secondary Education")
    assert canonical_board("ICSE") == canonical_board(
        "Council for the Indian School Certificate Examinations"
    )
    assert canonical_board("Unlisted Synthetic Board") is None


def resolve(
    existing,
    *,
    qualification="Class X",
    institution="Synthetic Board",
    year=2020,
):
    return resolve_education_entity(
        institution_name=institution,
        qualification=qualification,
        education_level="high_school",
        completion_year_value=year,
        educations=existing,
    )


def test_class_x_missing_year_matches_when_no_conflict_exists():
    row = education("High School", year=None)
    assert resolve([row], year=2020).state == "CLEAR_MATCH"


def test_class_x_school_name_and_board_evidence_are_not_a_conflict():
    row = education("Matriculation", institution="Synthetic Secondary School")
    result = resolve(
        [row], institution="Maharashtra State Board of Secondary and Higher Secondary Education"
    )
    assert result.state == "CLEAR_MATCH" and result.education_id == row.id


def test_conflicting_completion_year_requires_review():
    assert resolve([education("Class X", year=2019)], year=2020).state == "CONFLICT"


def test_conflicting_authoritative_board_requires_review():
    row = education("Class X", institution="CBSE")
    result = resolve(
        [row],
        institution="Maharashtra State Board of Secondary and Higher Secondary Education",
    )
    assert result.state == "CONFLICT"


def test_class_x_never_matches_class_xii():
    assert resolve([education("Class XII")]).state == "NO_MATCH"


def test_multiple_same_level_records_are_ambiguous():
    assert resolve([education("Class X"), education("SSC")]).state == "AMBIGUOUS"


def test_degree_matching_remains_strict_and_does_not_fuzzy_match():
    row = SimpleNamespace(
        id=uuid4(),
        institution_name="Synthetic University",
        degree="Bachelor of Commerce",
        field_of_study=None,
        education_level="bachelors",
        end_date=date(2020, 12, 31),
    )
    exact = resolve_education_entity(
        institution_name="Synthetic University",
        qualification="Bachelor of Commerce",
        education_level="bachelors",
        completion_year_value=2020,
        educations=[row],
    )
    different = resolve_education_entity(
        institution_name="Another University",
        qualification="Bachelor Commerce",
        education_level="bachelors",
        completion_year_value=2020,
        educations=[row],
    )
    assert exact.state == "CLEAR_MATCH"
    assert different.state == "NO_MATCH"
