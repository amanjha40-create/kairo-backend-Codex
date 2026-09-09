"""Header normalization and mapping contracts for roster M2."""

from __future__ import annotations

import pytest

from app.exceptions import ValidationAppError
from app.organization_roster_import.enums import OrganizationRosterType
from app.organization_roster_import.headers import (
    alias_dictionary,
    analyze_mapping,
    apply_manual_mapping,
    build_source_columns,
    normalize_header,
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("  Employee   ID ", "employee_id"),
        ("WORK-EMAIL", "work_email"),
        ("\ufeffStudent ID", "student_id"),
        ("Date.of Joining", "date_of_joining"),
    ],
)
def test_header_normalization_is_deterministic(source: str, expected: str) -> None:
    assert normalize_header(source) == expected


def test_employee_aliases_auto_map_without_multi_mapping() -> None:
    columns = build_source_columns(
        [
            "Staff Code",
            "Employee Name",
            "Corporate Email",
            "Dept",
            "Job Title",
            "Worker Type",
            "DOJ",
            "Last Working Date",
            "Employee Status",
            "Office Location",
        ]
    )
    result = analyze_mapping(OrganizationRosterType.EMPLOYEE, columns)
    assert set(result.mappings.values()) == {
        "employee_id",
        "full_name",
        "work_email",
        "department",
        "designation",
        "employment_type",
        "joining_date",
        "exit_date",
        "employment_status",
        "location",
    }
    assert result.requires_manual_mapping is False


def test_all_locked_employee_alias_examples_are_registered() -> None:
    aliases = alias_dictionary(OrganizationRosterType.EMPLOYEE)
    expected = {
        "emp_id": "employee_id",
        "employee_code": "employee_id",
        "surname": "last_name",
        "official_email": "work_email",
        "mobile_number": "phone",
        "role": "designation",
        "start_date": "joining_date",
        "end_date": "exit_date",
        "status": "employment_status",
        "work_location": "location",
    }
    assert {source: aliases[source] for source in expected} == expected


def test_student_aliases_auto_map() -> None:
    columns = build_source_columns(
        [
            "Registration No",
            "Roll No",
            "Student Name",
            "University Email",
            "Programme",
            "Major",
            "Date of Admission",
            "Completion Date",
            "Student Status",
            "Batch",
        ]
    )
    result = analyze_mapping(OrganizationRosterType.STUDENT, columns)
    assert set(result.mappings.values()) == {
        "student_id",
        "roll_number",
        "full_name",
        "institutional_email",
        "program",
        "specialization",
        "admission_date",
        "graduation_date",
        "enrollment_status",
        "cohort",
    }


def test_all_locked_student_alias_examples_are_registered() -> None:
    aliases = alias_dictionary(OrganizationRosterType.STUDENT)
    expected = {
        "student_code": "student_id",
        "registration_number": "student_id",
        "roll": "roll_number",
        "surname": "last_name",
        "college_email": "institutional_email",
        "phone_number": "phone",
        "course": "program",
        "major": "specialization",
        "start_date": "admission_date",
        "end_date": "graduation_date",
        "status": "enrollment_status",
        "batch": "cohort",
    }
    assert {source: aliases[source] for source in expected} == expected


def test_unknown_headers_remain_unmapped_and_missing_identity_is_reported() -> None:
    columns = build_source_columns(["Mystery Identifier", "Name"])
    result = analyze_mapping(OrganizationRosterType.EMPLOYEE, columns)
    assert result.unmapped_source_columns == ("mystery_identifier",)
    assert result.missing_required_mappings == ("identity",)
    assert result.requires_manual_mapping is True


def test_ambiguous_aliases_are_not_silently_collapsed() -> None:
    columns = build_source_columns(["Employee ID", "Emp ID", "Name"])
    result = analyze_mapping(OrganizationRosterType.EMPLOYEE, columns)
    assert "employee_id" in result.ambiguous_mappings
    assert "employee_id" not in result.mappings.values()
    assert result.requires_manual_mapping is True


def test_manual_mapping_and_explicit_unmapping() -> None:
    columns = build_source_columns(["Staff Number", "Person", "Email"])
    initial = analyze_mapping(OrganizationRosterType.EMPLOYEE, columns)
    mapped = apply_manual_mapping(
        OrganizationRosterType.EMPLOYEE,
        columns,
        initial.mappings,
        [("Staff Number", "employee_id"), ("Person", "full_name"), ("Email", "work_email")],
    )
    assert mapped.requires_manual_mapping is False
    unmapped = apply_manual_mapping(
        OrganizationRosterType.EMPLOYEE,
        columns,
        mapped.mappings,
        [("Staff Number", None)],
    )
    assert "staff_number" not in unmapped.mappings


@pytest.mark.parametrize(
    ("assignments", "code"),
    [
        ([("Missing", "employee_id")], "unknown_source_column"),
        ([("Name", "student_id")], "invalid_mapping_target"),
        ([("Work Email", "employee_id")], "incompatible_mapping"),
        ([("Name", "joining_date_precision")], "invalid_mapping_target"),
    ],
)
def test_manual_mapping_rejects_invalid_assignments(
    assignments: list[tuple[str, str]], code: str
) -> None:
    columns = build_source_columns(["Name", "Work Email"])
    current = analyze_mapping(OrganizationRosterType.EMPLOYEE, columns).mappings
    with pytest.raises(ValidationAppError) as caught:
        apply_manual_mapping(OrganizationRosterType.EMPLOYEE, columns, current, assignments)
    assert caught.value.code == code


def test_manual_mapping_rejects_duplicate_canonical_targets() -> None:
    columns = build_source_columns(["Person A", "Person B", "Employee ID"])
    with pytest.raises(ValidationAppError) as caught:
        apply_manual_mapping(
            OrganizationRosterType.EMPLOYEE,
            columns,
            {"employee_id": "employee_id"},
            [("Person A", "full_name"), ("Person B", "full_name")],
        )
    assert caught.value.code == "duplicate_mapping_target"


def test_manual_mapping_rejects_duplicate_source_assignments() -> None:
    columns = build_source_columns(["Person", "Employee ID"])
    with pytest.raises(ValidationAppError) as caught:
        apply_manual_mapping(
            OrganizationRosterType.EMPLOYEE,
            columns,
            {"employee_id": "employee_id"},
            [("Person", "full_name"), ("Person", None)],
        )
    assert caught.value.code == "duplicate_mapping_source"
