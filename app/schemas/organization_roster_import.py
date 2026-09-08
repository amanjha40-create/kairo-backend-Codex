"""HTTP contracts for roster upload and preview mapping."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.organization_roster_import.enums import (
    OrganizationRosterImportState,
    OrganizationRosterType,
)


class RosterMappingAssignment(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    source_column: str = Field(min_length=1, max_length=255)
    canonical_field: str | None = Field(default=None, max_length=64)


class RosterMappingUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignments: list[RosterMappingAssignment] = Field(min_length=1, max_length=64)


class RosterSourceColumnResponse(BaseModel):
    original: str
    normalized: str


class RosterMappingResponse(BaseModel):
    source_columns: list[RosterSourceColumnResponse]
    mappings: dict[str, str]
    unmapped_source_columns: list[str]
    missing_required_mappings: list[str]
    ambiguous_mappings: list[str]
    warnings: list[str]


class RosterRowIssueResponse(BaseModel):
    code: str
    field: str | None = None
    message: str
    row_number: int


class RosterPreviewRowResponse(BaseModel):
    row_number: int
    raw_values: dict[str, Any]
    normalized_values: dict[str, Any]
    disposition: str
    validation_errors: list[RosterRowIssueResponse]
    primary_identifier: str | None = None
    matched_organization_person_id: UUID | None = None


class RosterPreviewCountsResponse(BaseModel):
    total_rows: int
    valid_new: int
    valid_update: int
    duplicate: int
    invalid: int
    skipped: int
    created: int
    updated: int


class OrganizationRosterPreviewResponse(BaseModel):
    import_id: UUID
    roster_type: OrganizationRosterType
    source_format: str
    original_filename: str
    state: OrganizationRosterImportState
    selected_sheet_name: str | None = None
    selected_sheet_warning: str | None = None
    mapping: RosterMappingResponse
    counts: RosterPreviewCountsResponse
    rows: list[RosterPreviewRowResponse]
    parsed_at: datetime | None = None
    created_at: datetime
