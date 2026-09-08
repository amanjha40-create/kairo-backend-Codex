"""Pure helpers for safely applying organization-provided roster rows."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.models.organization_person import OrganizationPerson
from app.models.organization_person_roster_profile import OrganizationPersonRosterProfile
from app.organization_people.enums import (
    OrganizationPersonIdentifierType,
    OrganizationPersonRelationship,
)
from app.organization_roster_import.enums import OrganizationRosterType

EMPLOYEE_PROFILE_FIELDS = frozenset(
    {
        "employee_id",
        "department",
        "designation",
        "employment_type",
        "joining_date",
        "joining_date_precision",
        "exit_date",
        "exit_date_precision",
        "employment_status",
        "location",
    }
)
STUDENT_PROFILE_FIELDS = frozenset(
    {
        "student_id",
        "roll_number",
        "department",
        "degree",
        "program",
        "specialization",
        "admission_date",
        "admission_date_precision",
        "graduation_date",
        "graduation_date_precision",
        "enrollment_status",
        "campus",
        "cohort",
    }
)
DATE_VALUE_FIELDS = frozenset({"joining_date", "exit_date", "admission_date", "graduation_date"})


class RosterRowApplicationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def relationship_for_row(
    roster_type: OrganizationRosterType,
    values: dict[str, Any],
) -> OrganizationPersonRelationship:
    if roster_type is OrganizationRosterType.STUDENT:
        # OrganizationPersonRelationship.CANDIDATE is an organization registry
        # classification; it does not create or link a Candidate account.
        return OrganizationPersonRelationship.CANDIDATE
    if values.get("employment_status") in {"former", "inactive", "terminated"}:
        return OrganizationPersonRelationship.FORMER_EMPLOYEE
    if values.get("employment_type") in {"contract", "freelance", "gig"}:
        return OrganizationPersonRelationship.CONTRACTOR
    return OrganizationPersonRelationship.EMPLOYEE


def apply_person_values(
    person: OrganizationPerson,
    values: dict[str, Any],
    *,
    roster_type: OrganizationRosterType,
) -> None:
    if values.get("full_name"):
        person.full_name = str(values["full_name"])
    email_field = (
        "work_email" if roster_type is OrganizationRosterType.EMPLOYEE else "institutional_email"
    )
    if values.get(email_field):
        person.primary_email = str(values[email_field])
    if values.get("phone"):
        person.primary_phone = str(values["phone"])
    if roster_type is OrganizationRosterType.STUDENT or any(
        values.get(field) for field in ("employment_status", "employment_type")
    ):
        person.relationship = relationship_for_row(roster_type, values)


def apply_profile_values(
    profile: OrganizationPersonRosterProfile,
    values: dict[str, Any],
    *,
    roster_type: OrganizationRosterType,
) -> None:
    allowed = (
        EMPLOYEE_PROFILE_FIELDS
        if roster_type is OrganizationRosterType.EMPLOYEE
        else STUDENT_PROFILE_FIELDS
    )
    for field in allowed:
        value = values.get(field)
        if value is None or value == "":
            continue
        if field in DATE_VALUE_FIELDS:
            value = date.fromisoformat(str(value))
        setattr(profile, field, value)


def registry_identifiers(
    roster_type: OrganizationRosterType,
    values: dict[str, Any],
) -> tuple[tuple[OrganizationPersonIdentifierType, str], ...]:
    result: list[tuple[OrganizationPersonIdentifierType, str]] = []
    email_field = (
        "work_email" if roster_type is OrganizationRosterType.EMPLOYEE else "institutional_email"
    )
    if values.get(email_field):
        result.append((OrganizationPersonIdentifierType.EMAIL, str(values[email_field])))
    if values.get("phone"):
        result.append((OrganizationPersonIdentifierType.PHONE, str(values["phone"])))
    return tuple(result)


def roster_identity_fields(
    roster_type: OrganizationRosterType,
    values: dict[str, Any],
) -> tuple[tuple[str, str], ...]:
    fields = (
        ("employee_id",)
        if roster_type is OrganizationRosterType.EMPLOYEE
        else (
            "student_id",
            "roll_number",
        )
    )
    return tuple((field, str(values[field])) for field in fields if values.get(field))


def csv_safe(value: object | None) -> str:
    """Prevent exported cells from being interpreted as spreadsheet formulas."""

    rendered = "" if value is None else str(value)
    candidate = rendered.lstrip(" \t\r\n\ufeff")
    if candidate.startswith(("=", "+", "-", "@")) or rendered.startswith(("\t", "\r")):
        return f"'{rendered}"
    return rendered
