"""Internal immutable value objects for roster preview processing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SourceColumn:
    original: str
    normalized: str


@dataclass(frozen=True, slots=True)
class RowIssue:
    code: str
    field: str | None
    message: str
    row_number: int

    def as_dict(self) -> dict[str, str | int | None]:
        return {
            "code": self.code,
            "field": self.field,
            "message": self.message,
            "row_number": self.row_number,
        }


@dataclass(frozen=True, slots=True)
class ParsedSourceRow:
    row_number: int
    raw_values: dict[str, Any]
    parser_issues: tuple[RowIssue, ...] = ()
    skipped: bool = False


@dataclass(frozen=True, slots=True)
class ParsedRosterFile:
    source_format: str
    columns: tuple[SourceColumn, ...]
    rows: tuple[ParsedSourceRow, ...]
    sheet_name: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MappingAnalysis:
    mappings: dict[str, str]
    unmapped_source_columns: tuple[str, ...]
    missing_required_mappings: tuple[str, ...]
    ambiguous_mappings: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def requires_manual_mapping(self) -> bool:
        return bool(self.missing_required_mappings or self.ambiguous_mappings)


@dataclass(slots=True)
class PreviewRow:
    row_number: int
    raw_values: dict[str, Any]
    normalized_values: dict[str, Any] = field(default_factory=dict)
    disposition: str = "invalid"
    validation_errors: list[RowIssue] = field(default_factory=list)
    primary_identifier: str | None = None
    matched_organization_person_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class RegistryMatch:
    person_id: UUID | None = None
    conflicting_fields: tuple[str, ...] = ()

    @property
    def is_conflict(self) -> bool:
        return bool(self.conflicting_fields)
