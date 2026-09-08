"""Locked V1 limits and file contracts for organization roster imports."""

from __future__ import annotations

MAX_UPLOAD_BYTES = 5_000_000
MAX_DATA_ROWS = 10_000
MAX_COLUMNS = 64
MAX_CELL_LENGTH = 4_096
MAX_FILENAME_LENGTH = 255
MAX_XLSX_ARCHIVE_ENTRIES = 1_000
MAX_XLSX_UNCOMPRESSED_BYTES = 100_000_000
SOURCE_RETENTION_DAYS = 30

CSV_MIME_TYPES = frozenset(
    {
        "application/csv",
        "application/vnd.ms-excel",
        "text/csv",
        "text/plain",
    }
)
XLSX_MIME_TYPES = frozenset({"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})

SUPPORTED_EXTENSIONS = frozenset({".csv", ".xlsx"})

EMPLOYEE_FIELDS = frozenset(
    {
        "employee_id",
        "full_name",
        "first_name",
        "last_name",
        "work_email",
        "phone",
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

STUDENT_FIELDS = frozenset(
    {
        "student_id",
        "roll_number",
        "full_name",
        "first_name",
        "last_name",
        "institutional_email",
        "phone",
        "degree",
        "program",
        "specialization",
        "department",
        "admission_date",
        "admission_date_precision",
        "graduation_date",
        "graduation_date_precision",
        "enrollment_status",
        "campus",
        "cohort",
    }
)

DATE_FIELDS = frozenset({"joining_date", "exit_date", "admission_date", "graduation_date"})
DATE_PRECISION_FIELDS = frozenset(
    {
        "joining_date_precision",
        "exit_date_precision",
        "admission_date_precision",
        "graduation_date_precision",
    }
)
EMAIL_FIELDS = frozenset({"work_email", "institutional_email"})
IDENTIFIER_FIELDS = frozenset({"employee_id", "student_id", "roll_number"})

PARSER_ERROR_CODES = frozenset({"malformed_row"})
