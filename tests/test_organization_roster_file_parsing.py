"""File-safety and deterministic parser coverage for roster M2."""

from __future__ import annotations

from datetime import date
from io import BytesIO

import pytest
from openpyxl import Workbook

from app.exceptions import ValidationAppError
from app.organization_roster_import.constants import (
    MAX_CELL_LENGTH,
    MAX_COLUMNS,
    MAX_DATA_ROWS,
    MAX_UPLOAD_BYTES,
)
from app.organization_roster_import.parsing import parse_roster_file


def _parse_csv(text: str, **overrides):  # noqa: ANN003, ANN202
    return parse_roster_file(
        filename=overrides.get("filename", "employees.csv"),
        content_type=overrides.get("content_type", "text/csv"),
        content=text.encode("utf-8"),
    )[1]


def _workbook_bytes(*sheets: tuple[str, list[list[object]]]) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets:
        sheet = workbook.create_sheet(title)
        for row in rows:
            sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_csv_and_utf8_bom_are_supported() -> None:
    parsed = _parse_csv("\ufeffEmployee ID,Full Name\n001,José Rao\n")
    assert parsed.source_format == "csv"
    assert parsed.columns[0].normalized == "employee_id"
    assert parsed.rows[0].row_number == 2
    assert parsed.rows[0].raw_values["Employee ID"] == "001"


@pytest.mark.parametrize(
    ("filename", "content_type", "code"),
    [
        ("employees.txt", "text/plain", "unsupported_file"),
        ("employees.csv", "application/pdf", "unsupported_mime_type"),
        ("x" * 252 + ".csv", "text/csv", "invalid_filename"),
        ("../employees.csv", "text/csv", "unsafe_filename"),
        ("folder\\employees.csv", "text/csv", "unsafe_filename"),
    ],
)
def test_unsafe_or_unsupported_uploads_are_rejected(
    filename: str, content_type: str, code: str
) -> None:
    with pytest.raises(ValidationAppError) as caught:
        parse_roster_file(
            filename=filename,
            content_type=content_type,
            content=b"Employee ID,Full Name\n1,Test",
        )
    assert caught.value.code == code


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"", "empty_file"),
        (b"Employee ID,Full Name\n", "no_usable_rows"),
        (b"\xff\xfe\x00", "invalid_csv_encoding"),
    ],
)
def test_empty_or_unusable_csv_is_rejected(content: bytes, code: str) -> None:
    with pytest.raises(ValidationAppError) as caught:
        parse_roster_file(filename="employees.csv", content_type="text/csv", content=content)
    assert caught.value.code == code


def test_upload_size_limit_is_enforced() -> None:
    with pytest.raises(ValidationAppError) as caught:
        parse_roster_file(
            filename="employees.csv",
            content_type="text/csv",
            content=b"x" * (MAX_UPLOAD_BYTES + 1),
        )
    assert caught.value.code == "file_too_large"


def test_column_and_cell_limits_are_enforced() -> None:
    headers = ",".join(f"h{index}" for index in range(MAX_COLUMNS + 1))
    with pytest.raises(ValidationAppError) as columns_error:
        _parse_csv(f"{headers}\n{','.join('x' for _ in range(MAX_COLUMNS + 1))}")
    assert columns_error.value.code == "too_many_columns"

    with pytest.raises(ValidationAppError) as cell_error:
        _parse_csv(f"Employee ID,Full Name\n1,{'x' * (MAX_CELL_LENGTH + 1)}")
    assert cell_error.value.code == "cell_too_long"


def test_row_limit_is_enforced() -> None:
    data = "Employee ID,Full Name\n" + "\n".join(
        f"{index},Person {index}" for index in range(MAX_DATA_ROWS + 1)
    )
    with pytest.raises(ValidationAppError) as caught:
        _parse_csv(data)
    assert caught.value.code == "too_many_rows"


def test_duplicate_normalized_headers_are_rejected() -> None:
    with pytest.raises(ValidationAppError) as caught:
        _parse_csv(" Employee ID ,employee-id\n1,2")
    assert caught.value.code == "duplicate_header"


def test_malformed_csv_and_malformed_row_are_distinct() -> None:
    with pytest.raises(ValidationAppError) as caught:
        _parse_csv('Employee ID,Full Name\n1,"unterminated')
    assert caught.value.code == "malformed_csv"

    parsed = _parse_csv("Employee ID,Full Name,Department\n1,Test\n")
    assert parsed.rows[0].parser_issues[0].code == "malformed_row"
    assert parsed.rows[0].row_number == 2


def test_blank_trailing_rows_are_removed_but_interior_blank_is_preserved() -> None:
    parsed = _parse_csv("Employee ID,Full Name\n1,One\n,\n2,Two\n,\n")
    assert [row.row_number for row in parsed.rows] == [2, 3, 4]
    assert parsed.rows[1].skipped is True


def test_csv_formula_text_is_never_executed() -> None:
    parsed = _parse_csv('Employee ID,Full Name\n1,=HYPERLINK("https://invalid")')
    assert parsed.rows[0].raw_values["Full Name"].startswith("=HYPERLINK")


def test_csv_multiline_record_preserves_its_starting_source_line() -> None:
    parsed = _parse_csv('Employee ID,Full Name\n1,"Multi\nLine"\n2,Second\n')
    assert [row.row_number for row in parsed.rows] == [2, 4]


def test_xlsx_selects_first_non_empty_sheet_and_warns_about_others() -> None:
    content = _workbook_bytes(
        ("Empty", []),
        ("Employees", [["Employee ID", "Full Name"], ["001", "Aman"]]),
        ("Ignored", [["Employee ID", "Full Name"], ["002", "Other"]]),
    )
    parsed = parse_roster_file(
        filename="employees.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        content=content,
    )[1]
    assert parsed.sheet_name == "Employees"
    assert parsed.rows[0].row_number == 2
    assert parsed.warnings == ("Additional non-empty worksheets were not imported",)


def test_xlsx_preserves_physical_row_numbers_and_dates() -> None:
    content = _workbook_bytes(
        (
            "Roster",
            [[], ["Employee ID", "Full Name", "Joining Date"], ["001", "Aman", date(2022, 8, 15)]],
        )
    )
    parsed = parse_roster_file(
        filename="employees.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        content=content,
    )[1]
    assert parsed.rows[0].row_number == 3
    assert parsed.rows[0].raw_values["Joining Date"] == "2022-08-15"


def test_xlsx_formula_is_returned_as_text_not_a_calculated_value() -> None:
    content = _workbook_bytes(
        ("Roster", [["Employee ID", "Full Name"], ["001", '=CONCAT("A","B")']])
    )
    parsed = parse_roster_file(
        filename="employees.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        content=content,
    )[1]
    assert parsed.rows[0].raw_values["Full Name"] == '=CONCAT("A","B")'


def test_xlsx_column_and_cell_limits_are_enforced() -> None:
    wide = [f"Column {index}" for index in range(MAX_COLUMNS + 1)]
    with pytest.raises(ValidationAppError) as columns_error:
        parse_roster_file(
            filename="employees.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content=_workbook_bytes(("Roster", [wide, ["x"] * len(wide)])),
        )
    assert columns_error.value.code in {"too_many_columns", "workbook_too_large"}

    with pytest.raises(ValidationAppError) as cell_error:
        parse_roster_file(
            filename="employees.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content=_workbook_bytes(
                ("Roster", [["Employee ID", "Full Name"], ["1", "x" * (MAX_CELL_LENGTH + 1)]])
            ),
        )
    assert cell_error.value.code == "cell_too_long"


def test_xlsx_row_limit_is_enforced() -> None:
    rows = [["Employee ID", "Full Name"]]
    rows.extend([[str(index), "Name"] for index in range(MAX_DATA_ROWS + 1)])
    with pytest.raises(ValidationAppError) as caught:
        parse_roster_file(
            filename="employees.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content=_workbook_bytes(("Roster", rows)),
        )
    assert caught.value.code == "workbook_too_large"


@pytest.mark.parametrize(
    ("content", "expected_code"),
    [
        (b"not-a-zip", "invalid_xlsx"),
        (bytes.fromhex("D0CF11E0A1B11AE1") + b"encrypted", "encrypted_workbook"),
    ],
)
def test_corrupt_and_encrypted_workbooks_are_rejected(content: bytes, expected_code: str) -> None:
    with pytest.raises(ValidationAppError) as caught:
        parse_roster_file(
            filename="employees.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content=content,
        )
    assert caught.value.code == expected_code


def test_empty_workbook_is_rejected() -> None:
    with pytest.raises(ValidationAppError) as caught:
        parse_roster_file(
            filename="employees.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content=_workbook_bytes(("Empty", [])),
        )
    assert caught.value.code == "empty_workbook"
