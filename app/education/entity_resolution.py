"""Deterministic Education entity resolution shared across import sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol
from uuid import UUID

from app.resumes.normalization import normalize_text


class EducationLike(Protocol):
    id: UUID
    institution_name: str
    degree: str | None
    field_of_study: str | None
    education_level: str | None
    end_date: object | None


_CLASS_X = frozenset(
    {
        "class x",
        "class 10",
        "10",
        "10th",
        "10th standard",
        "high school",
        "secondary",
        "secondary school",
        "matriculation",
        "matric",
        "ssc",
    }
)
_CLASS_XII = frozenset(
    {
        "class xii",
        "class 12",
        "12",
        "12th",
        "12th standard",
        "higher secondary",
        "senior secondary",
        "hsc",
    }
)

_BOARD_ALIASES = {
    "cbse": "board:cbse",
    "central board of secondary education": "board:cbse",
    "cisce": "board:cisce",
    "council for the indian school certificate examinations": "board:cisce",
    "icse": "board:cisce",
    "indian certificate of secondary education": "board:cisce",
    "msbshse": "board:maharashtra",
    "maharashtra state board of secondary and higher secondary education": (
        "board:maharashtra"
    ),
    "maharashtra state board of secondary higher secondary education": (
        "board:maharashtra"
    ),
}


def canonical_education_level(*values: str | None) -> str | None:
    """Return only deterministic semantic levels; never fuzzy-match qualifications."""
    normalized = [normalize_text(value) for value in values if value]
    for value in normalized:
        if value in _CLASS_X:
            return "class_x"
        if value in _CLASS_XII:
            return "class_xii"
    for value in normalized:
        if value and value != "high school":
            return f"qualification:{value}"
    return None


def canonical_board(value: str | None) -> str | None:
    """Resolve only approved authoritative aliases, including harmless location suffixes."""
    normalized = normalize_text(value)
    if not normalized:
        return None
    direct = _BOARD_ALIASES.get(normalized)
    if direct:
        return direct
    for alias, canonical in _BOARD_ALIASES.items():
        if len(alias) > 12 and normalized.startswith(alias + " "):
            return canonical
    return None


def completion_year(value: object | None) -> int | None:
    year = getattr(value, "year", None)
    return year if isinstance(year, int) else None


@dataclass(frozen=True, slots=True)
class EducationResolution:
    state: str
    education_id: UUID | None = None
    reason: str = ""


def resolve_education_entity(
    *,
    institution_name: str | None,
    qualification: str | None,
    education_level: str | None,
    completion_year_value: int | None,
    educations: Iterable[EducationLike],
) -> EducationResolution:
    """Resolve one provider record without treating missing optional data as conflict."""
    rows = list(educations)
    incoming_level = canonical_education_level(qualification, education_level)
    if incoming_level is None:
        return EducationResolution("NO_MATCH", reason="education_level_missing")

    if incoming_level in {"class_x", "class_xii"}:
        same_level = [
            row
            for row in rows
            if canonical_education_level(row.degree, row.field_of_study, row.education_level)
            == incoming_level
        ]
        if not same_level:
            return EducationResolution("NO_MATCH", reason="education_level_absent")
        if len(same_level) > 1:
            return EducationResolution("AMBIGUOUS", reason="multiple_level_candidates")

        existing = same_level[0]
        incoming_board = canonical_board(institution_name)
        existing_board = canonical_board(existing.institution_name)
        if incoming_board and existing_board and incoming_board != existing_board:
            return EducationResolution("CONFLICT", reason="board_conflict")
        existing_year = completion_year(existing.end_date)
        if (
            completion_year_value is not None
            and existing_year is not None
            and completion_year_value != existing_year
        ):
            return EducationResolution("CONFLICT", reason="completion_year_conflict")
        return EducationResolution("CLEAR_MATCH", existing.id, "single_compatible_level")

    institution = normalize_text(institution_name)
    qualification_key = normalize_text(qualification)
    if not institution or not qualification_key:
        return EducationResolution("NO_MATCH", reason="qualification_identity_missing")
    matches = []
    conflicts = False
    for existing in rows:
        if normalize_text(existing.institution_name) != institution:
            continue
        if normalize_text(existing.degree or existing.field_of_study) != qualification_key:
            continue
        existing_year = completion_year(existing.end_date)
        if (
            completion_year_value is not None
            and existing_year is not None
            and completion_year_value != existing_year
        ):
            conflicts = True
            continue
        matches.append(existing)
    if len(matches) == 1:
        return EducationResolution("CLEAR_MATCH", matches[0].id, "exact_qualification_identity")
    if len(matches) > 1:
        return EducationResolution("AMBIGUOUS", reason="multiple_exact_candidates")
    if conflicts:
        return EducationResolution("CONFLICT", reason="completion_year_conflict")
    return EducationResolution("NO_MATCH", reason="qualification_identity_absent")
