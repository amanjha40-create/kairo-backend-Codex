"""Shared pagination, sorting, and filter primitives for repositories."""

from __future__ import annotations

from enum import StrEnum


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class EmploymentSortField(StrEnum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    SUBMITTED_AT = "submitted_at"


class EmploymentDocumentSortField(StrEnum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    BYTE_SIZE = "byte_size"
