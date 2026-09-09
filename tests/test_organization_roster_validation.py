"""Normalization, validation, duplicate, and registry preview coverage."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.organization_roster_import.enums import OrganizationRosterType
from app.organization_roster_import.headers import analyze_mapping, build_source_columns
from app.organization_roster_import.normalization import normalize_row_values, parse_date_value
from app.organization_roster_import.preview import build_preview
from app.organization_roster_import.types import (
    ParsedRosterFile,
    ParsedSourceRow,
    RegistryMatch,
)


@pytest.mark.parametrize(
    ("raw", "expected", "precision"),
    [
        ("2022", date(2022, 1, 1), "year"),
        (2022, date(2022, 1, 1), "year"),
        ("Aug 2022", date(2022, 8, 1), "month"),
        ("August 2022", date(2022, 8, 1), "month"),
        ("2022-08", date(2022, 8, 1), "month"),
        ("2022-08-15", date(2022, 8, 15), "day"),
        ("15/08/2022", date(2022, 8, 15), "day"),
        (date(2022, 8, 15), date(2022, 8, 15), "day"),
    ],
)
def test_date_precision_is_never_fabricated(raw: object, expected: date, precision: str) -> None:
    parsed, parsed_precision = parse_date_value(raw)
    assert parsed == expected
    assert parsed_precision.value == precision


def test_invalid_date_is_rejected() -> None:
    with pytest.raises(ValueError):
        parse_date_value("08/15/2022")


def test_employee_values_are_normalized_conservatively() -> None:
    normalized, issues = normalize_row_values(
        {
            "employee_id": " 0012 ",
            "first_name": "  Mary-Jane ",
            "last_name": " O'Neil  ",
            "work_email": " PERSON@Example.COM ",
            "phone": "+91 98765-43210",
            "employment_type": "Full Time",
            "employment_status": "Current",
            "joining_date": "Aug 2022",
        },
        row_number=2,
        roster_type=OrganizationRosterType.EMPLOYEE,
    )
    assert issues == []
    assert normalized["employee_id"] == "0012"
    assert normalized["full_name"] == "Mary-Jane O'Neil"
    assert normalized["work_email"] == "person@example.com"
    assert normalized["phone"] == "+919876543210"
    assert normalized["employment_type"] == "full_time"
    assert normalized["employment_status"] == "active"
    assert normalized["joining_date"]["precision"] == "month"


def test_student_enum_and_blanks_normalize() -> None:
    normalized, issues = normalize_row_values(
        {
            "student_id": "S-1",
            "full_name": " Student Name ",
            "enrollment_status": "Completed",
            "campus": "  ",
        },
        row_number=2,
        roster_type=OrganizationRosterType.STUDENT,
    )
    assert issues == []
    assert normalized["enrollment_status"] == "graduated"
    assert "campus" not in normalized


@pytest.mark.parametrize(
    ("values", "error_code"),
    [
        ({"full_name": "Name"}, "missing_identity"),
        ({"employee_id": "1"}, "missing_name"),
        ({"employee_id": 1.5, "full_name": "Name"}, "invalid_identifier"),
        ({"employee_id": "1", "full_name": "Name", "work_email": "bad"}, "invalid_email"),
        ({"employee_id": "1", "full_name": "Name", "phone": "9876543210"}, "invalid_phone"),
        (
            {"employee_id": "1", "full_name": "Name", "employment_type": "invented"},
            "invalid_enum",
        ),
        (
            {"employee_id": "1", "full_name": "Name", "designation": "x" * 256},
            "value_too_long",
        ),
        (
            {
                "employee_id": "1",
                "full_name": "Name",
                "joining_date": "2024",
                "exit_date": "2023",
            },
            "invalid_chronology",
        ),
    ],
)
def test_structured_employee_validation_errors(values: dict[str, object], error_code: str) -> None:
    _, issues = normalize_row_values(
        values,
        row_number=7,
        roster_type=OrganizationRosterType.EMPLOYEE,
    )
    assert error_code in {issue.code for issue in issues}
    assert all(issue.row_number == 7 for issue in issues)


def test_student_chronology_is_validated_with_null_end_allowed() -> None:
    valid, valid_issues = normalize_row_values(
        {"student_id": "1", "full_name": "Name", "admission_date": "2022"},
        row_number=2,
        roster_type=OrganizationRosterType.STUDENT,
    )
    assert "graduation_date" not in valid
    assert valid_issues == []
    _, invalid_issues = normalize_row_values(
        {
            "student_id": "1",
            "full_name": "Name",
            "admission_date": "2022",
            "graduation_date": "2021",
        },
        row_number=3,
        roster_type=OrganizationRosterType.STUDENT,
    )
    assert {issue.code for issue in invalid_issues} == {"invalid_chronology"}


def test_partial_date_chronology_uses_precision_ranges() -> None:
    _, same_year_issues = normalize_row_values(
        {
            "employee_id": "1",
            "full_name": "Name",
            "joining_date": "Aug 2022",
            "exit_date": "2022",
        },
        row_number=2,
        roster_type=OrganizationRosterType.EMPLOYEE,
    )
    assert same_year_issues == []

    _, earlier_month_issues = normalize_row_values(
        {
            "employee_id": "1",
            "full_name": "Name",
            "joining_date": "Aug 2022",
            "exit_date": "Jul 2022",
        },
        row_number=3,
        roster_type=OrganizationRosterType.EMPLOYEE,
    )
    assert {issue.code for issue in earlier_month_issues} == {"invalid_chronology"}


def _parsed(headers: list[str], values: list[list[object]]) -> ParsedRosterFile:
    columns = build_source_columns(headers)
    return ParsedRosterFile(
        source_format="csv",
        columns=columns,
        rows=tuple(
            ParsedSourceRow(
                row_number=index,
                raw_values=dict(zip(headers, row, strict=True)),
            )
            for index, row in enumerate(values, start=2)
        ),
    )


@pytest.mark.parametrize(
    ("roster_type", "headers", "rows"),
    [
        ("employee", ["Employee ID", "Full Name"], [["1", "Name"], ["1", "Name"]]),
        (
            "employee",
            ["Work Email", "Full Name"],
            [["same@example.com", "Name"], ["SAME@example.com", "Name"]],
        ),
        ("student", ["Student ID", "Full Name"], [["1", "Name"], ["1", "Name"]]),
        ("student", ["Roll No", "Full Name"], [["1", "Name"], ["1", "Name"]]),
        (
            "student",
            ["Institutional Email", "Full Name"],
            [["same@example.com", "Name"], ["SAME@example.com", "Name"]],
        ),
    ],
)
async def test_redundant_in_file_identifiers_mark_later_row_duplicate(
    roster_type: str, headers: list[str], rows: list[list[object]]
) -> None:
    source = _parsed(headers, rows)
    mapping = analyze_mapping(roster_type, source.columns)
    result = await build_preview(source, mapping, roster_type)
    assert [row.disposition for row in result.rows] == ["valid_new", "duplicate"]
    assert result.duplicate_count == 1


async def test_conflicting_repeated_identifier_invalidates_all_conflicting_rows() -> None:
    source = _parsed(
        ["Employee ID", "Work Email", "Full Name"],
        [["1", "first@example.com", "One"], ["1", "second@example.com", "Two"]],
    )
    result = await build_preview(
        source,
        analyze_mapping("employee", source.columns),
        "employee",
    )
    assert [row.disposition for row in result.rows] == ["invalid", "invalid"]
    assert all(row.validation_errors[-1].code == "conflicting_duplicate" for row in result.rows)


async def test_registry_outcomes_are_new_update_or_conflict_without_name_matching() -> None:
    source = _parsed(
        ["Employee ID", "Full Name"],
        [["new", "Existing Name"], ["existing", "Other Name"], ["conflict", "Third Name"]],
    )
    person_id = uuid4()

    async def matcher(values: dict[str, object]) -> RegistryMatch:
        if values["employee_id"] == "existing":
            return RegistryMatch(person_id=person_id)
        if values["employee_id"] == "conflict":
            return RegistryMatch(conflicting_fields=("employee_id", "work_email"))
        return RegistryMatch()

    result = await build_preview(
        source,
        analyze_mapping("employee", source.columns),
        "employee",
        registry_matcher=matcher,
    )
    assert [row.disposition for row in result.rows] == [
        "valid_new",
        "valid_update",
        "invalid",
    ]
    assert result.rows[1].matched_organization_person_id == person_id
    assert result.rows[0].matched_organization_person_id is None
    assert result.rows[2].validation_errors[-1].code == "registry_identity_conflict"


async def test_mapping_incomplete_rows_are_invalid_and_counts_are_deterministic() -> None:
    source = _parsed(["Mystery", "Name"], [["1", "Name"]])
    result = await build_preview(
        source,
        analyze_mapping("employee", source.columns),
        "employee",
    )
    assert result.total_rows == 1
    assert result.invalid_count == 1
    assert "mapping_incomplete" in {issue.code for issue in result.rows[0].validation_errors}
