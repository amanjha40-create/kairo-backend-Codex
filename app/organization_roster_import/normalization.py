"""Canonical, conservative roster cell normalization."""

from __future__ import annotations

import math
import re
from calendar import monthrange
from datetime import date, datetime
from typing import Any

from pydantic import EmailStr, TypeAdapter, ValidationError

from app.employment.enums import EmploymentType
from app.organization_roster_import.constants import DATE_FIELDS, EMAIL_FIELDS, IDENTIFIER_FIELDS
from app.organization_roster_import.enums import (
    OrganizationRosterDatePrecision,
    OrganizationRosterType,
)
from app.organization_roster_import.types import RowIssue

_EMAIL_ADAPTER = TypeAdapter(EmailStr)
_SPACE_RE = re.compile(r"\s+")
_PHONE_FORMAT_RE = re.compile(r"[\s().-]+")
_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")

_MAX_LENGTHS: dict[str, int] = {
    "employee_id": 128,
    "student_id": 128,
    "roll_number": 128,
    "full_name": 255,
    "first_name": 128,
    "last_name": 128,
    "work_email": 320,
    "institutional_email": 320,
    "phone": 32,
    "department": 255,
    "designation": 255,
    "employment_type": 64,
    "employment_status": 64,
    "location": 255,
    "degree": 255,
    "program": 255,
    "specialization": 255,
    "enrollment_status": 64,
    "campus": 255,
    "cohort": 128,
}

_EMPLOYMENT_TYPE_ALIASES = {
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
_EMPLOYMENT_STATUS_ALIASES = {
    "active": "active",
    "current": "active",
    "employed": "active",
    "inactive": "inactive",
    "former": "former",
    "ex_employee": "former",
    "left": "former",
    "on_leave": "on_leave",
    "leave": "on_leave",
    "terminated": "terminated",
}
_ENROLLMENT_STATUS_ALIASES = {
    "enrolled": "enrolled",
    "active": "enrolled",
    "current": "enrolled",
    "graduated": "graduated",
    "completed": "graduated",
    "withdrawn": "withdrawn",
    "deferred": "deferred",
    "inactive": "inactive",
}


def normalize_row_values(
    mapped_values: dict[str, Any],
    *,
    row_number: int,
    roster_type: OrganizationRosterType | str,
) -> tuple[dict[str, Any], list[RowIssue]]:
    normalized: dict[str, Any] = {}
    issues: list[RowIssue] = []
    for field, raw_value in mapped_values.items():
        value, issue = normalize_value(field, raw_value, row_number=row_number)
        if value is not None:
            normalized[field] = value
        if issue is not None:
            issues.append(issue)

    if not normalized.get("full_name"):
        name_parts = [normalized.get("first_name"), normalized.get("last_name")]
        combined = " ".join(part for part in name_parts if part)
        if combined:
            normalized["full_name"] = combined

    _validate_required_identity_and_name(normalized, row_number, issues, roster_type)
    _validate_chronology(normalized, row_number, issues)
    return normalized, issues


def normalize_value(
    field: str,
    raw_value: Any,
    *,
    row_number: int,
) -> tuple[Any, RowIssue | None]:
    if _is_blank(raw_value):
        return None, None
    if field in IDENTIFIER_FIELDS:
        if isinstance(raw_value, (bool, float)):
            return None, _issue("invalid_identifier", field, "Identifier must be text", row_number)
        value = str(raw_value).strip()
        return _length_checked(field, value, row_number)
    if field in EMAIL_FIELDS:
        value = str(raw_value).strip().casefold()
        try:
            normalized = str(_EMAIL_ADAPTER.validate_python(value)).casefold()
        except ValidationError:
            return None, _issue("invalid_email", field, "Email address is invalid", row_number)
        return _length_checked(field, normalized, row_number)
    if field == "phone":
        value = str(raw_value).strip()
        if value.startswith("00"):
            value = f"+{value[2:]}"
        value = _PHONE_FORMAT_RE.sub("", value)
        if not _E164_RE.fullmatch(value):
            return None, _issue(
                "invalid_phone",
                field,
                "Phone must include an unambiguous country code",
                row_number,
            )
        return _length_checked(field, value, row_number)
    if field in DATE_FIELDS:
        try:
            parsed_date, precision = parse_date_value(raw_value)
        except ValueError:
            return None, _issue("invalid_date", field, "Date is invalid", row_number)
        return {
            "value": parsed_date.isoformat(),
            "precision": precision.value,
        }, None
    if field in {"full_name", "first_name", "last_name"}:
        return _length_checked(field, _SPACE_RE.sub(" ", str(raw_value).strip()), row_number)
    if field == "employment_type":
        return _normalize_enum(field, raw_value, _EMPLOYMENT_TYPE_ALIASES, row_number)
    if field == "employment_status":
        return _normalize_enum(field, raw_value, _EMPLOYMENT_STATUS_ALIASES, row_number)
    if field == "enrollment_status":
        return _normalize_enum(field, raw_value, _ENROLLMENT_STATUS_ALIASES, row_number)
    return _length_checked(field, _SPACE_RE.sub(" ", str(raw_value).strip()), row_number)


def parse_date_value(raw_value: Any) -> tuple[date, OrganizationRosterDatePrecision]:
    if isinstance(raw_value, datetime):
        return raw_value.date(), OrganizationRosterDatePrecision.DAY
    if isinstance(raw_value, date):
        return raw_value, OrganizationRosterDatePrecision.DAY
    if isinstance(raw_value, (float, int)) and not isinstance(raw_value, bool):
        if isinstance(raw_value, float) and (
            not math.isfinite(raw_value) or not raw_value.is_integer()
        ):
            raise ValueError("invalid numeric date")
        raw_value = str(int(raw_value))
    value = str(raw_value).strip()
    if re.fullmatch(r"\d{4}", value):
        return date(int(value), 1, 1), OrganizationRosterDatePrecision.YEAR
    for fmt in ("%b %Y", "%B %Y", "%Y-%m"):
        try:
            parsed = datetime.strptime(value, fmt).date()
            return parsed.replace(day=1), OrganizationRosterDatePrecision.MONTH
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date(), OrganizationRosterDatePrecision.DAY
        except ValueError:
            pass
    raise ValueError("unrecognized date")


def _validate_required_identity_and_name(
    normalized: dict[str, Any],
    row_number: int,
    issues: list[RowIssue],
    roster_type: OrganizationRosterType | str,
) -> None:
    employee_identity = normalized.get("employee_id") or normalized.get("work_email")
    student_identity = (
        normalized.get("student_id")
        or normalized.get("roll_number")
        or normalized.get("institutional_email")
    )
    if not (
        employee_identity
        if OrganizationRosterType(roster_type) is OrganizationRosterType.EMPLOYEE
        else student_identity
    ):
        issues.append(
            _issue("missing_identity", None, "A supported identity is required", row_number)
        )
    if not normalized.get("full_name"):
        issues.append(_issue("missing_name", "full_name", "A usable name is required", row_number))


def _validate_chronology(
    normalized: dict[str, Any], row_number: int, issues: list[RowIssue]
) -> None:
    for start, end in (("joining_date", "exit_date"), ("admission_date", "graduation_date")):
        if start not in normalized or end not in normalized:
            continue
        start_earliest = date.fromisoformat(normalized[start]["value"])
        end_latest = _latest_possible_date(normalized[end])
        if end_latest < start_earliest:
            issues.append(
                _issue("invalid_chronology", end, "End date cannot precede start date", row_number)
            )


def _latest_possible_date(value: dict[str, str]) -> date:
    parsed = date.fromisoformat(value["value"])
    if value["precision"] == OrganizationRosterDatePrecision.YEAR.value:
        return date(parsed.year, 12, 31)
    if value["precision"] == OrganizationRosterDatePrecision.MONTH.value:
        return date(parsed.year, parsed.month, monthrange(parsed.year, parsed.month)[1])
    return parsed


def flatten_normalized_dates(values: dict[str, Any]) -> dict[str, Any]:
    """Convert internal date objects to the M1 JSON ledger shape."""

    flattened: dict[str, Any] = {}
    for field, value in values.items():
        if field in DATE_FIELDS and isinstance(value, dict):
            flattened[field] = value["value"]
            flattened[f"{field}_precision"] = value["precision"]
        else:
            flattened[field] = value
    return flattened


def _normalize_enum(
    field: str,
    raw_value: Any,
    aliases: dict[str, str],
    row_number: int,
) -> tuple[str | None, RowIssue | None]:
    key = re.sub(r"[^a-z0-9]+", "_", str(raw_value).strip().casefold()).strip("_")
    normalized = aliases.get(key)
    if normalized is None:
        return None, _issue("invalid_enum", field, "Value is not supported", row_number)
    return normalized, None


def _length_checked(field: str, value: str, row_number: int) -> tuple[str | None, RowIssue | None]:
    maximum = _MAX_LENGTHS.get(field, 255)
    if len(value) > maximum:
        return None, _issue("value_too_long", field, "Value exceeds the field limit", row_number)
    return value or None, None


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _issue(code: str, field: str | None, message: str, row_number: int) -> RowIssue:
    return RowIssue(code=code, field=field, message=message, row_number=row_number)
