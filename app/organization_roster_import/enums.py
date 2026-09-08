"""Organization-owned bulk roster import contracts."""

from enum import StrEnum


class OrganizationRosterType(StrEnum):
    EMPLOYEE = "employee"
    STUDENT = "student"


class OrganizationRosterImportState(StrEnum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    MAPPING_REQUIRED = "mapping_required"
    READY_FOR_REVIEW = "ready_for_review"
    IMPORTING = "importing"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class OrganizationRosterRowDisposition(StrEnum):
    VALID_NEW = "valid_new"
    VALID_UPDATE = "valid_update"
    DUPLICATE = "duplicate"
    INVALID = "invalid"
    SKIPPED = "skipped"


class OrganizationRosterDatePrecision(StrEnum):
    YEAR = "year"
    MONTH = "month"
    DAY = "day"
