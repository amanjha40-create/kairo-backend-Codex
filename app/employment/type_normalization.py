"""Canonical normalization for employment types extracted from resumes."""

from __future__ import annotations

import re

from app.employment.enums import EmploymentType

_SEPARATOR_RE = re.compile(r"[^a-z0-9]+")

_ALIASES: dict[str, str] = {
    "full_time": EmploymentType.FULL_TIME.value,
    "fulltime": EmploymentType.FULL_TIME.value,
    "permanent": EmploymentType.FULL_TIME.value,
    "part_time": EmploymentType.PART_TIME.value,
    "parttime": EmploymentType.PART_TIME.value,
    "contract": EmploymentType.CONTRACT.value,
    "contractor": EmploymentType.CONTRACT.value,
    "intern": EmploymentType.INTERN.value,
    "internship": EmploymentType.INTERN.value,
    "gig": EmploymentType.GIG.value,
    "freelance": EmploymentType.FREELANCE.value,
    "freelancer": EmploymentType.FREELANCE.value,
    "other": EmploymentType.OTHER.value,
}


def normalize_employment_type(value: EmploymentType | str | None) -> str | None:
    """Return a canonical type only when the source value is recognized."""

    if isinstance(value, EmploymentType):
        return value.value
    if not isinstance(value, str):
        return None
    token = _SEPARATOR_RE.sub("_", value.strip().casefold()).strip("_")
    if not token:
        return None
    return _ALIASES.get(token)
