"""HTTP contracts for roster upload and preview mapping."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.organization_roster_import.enums import (
    OrganizationRosterAuditAction,
    OrganizationRosterImportState,
    OrganizationRosterRowApplicationStatus,
    OrganizationRosterRowDisposition,
    OrganizationRosterType,
)
from app.schemas.pagination import PageParams


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
    result_organization_person_id: UUID | None = None
    application_status: OrganizationRosterRowApplicationStatus
    application_errors: list[RosterRowIssueResponse]
    applied_at: datetime | None = None


class RosterPreviewCountsResponse(BaseModel):
    total_rows: int
    valid_new: int
    valid_update: int
    duplicate: int
    invalid: int
    skipped: int
    created: int
    updated: int
    failed: int


class RosterUploaderResponse(BaseModel):
    user_id: UUID
    display_name: str
    email: str


class RosterAuditEventResponse(BaseModel):
    event_id: UUID
    action: OrganizationRosterAuditAction
    organization_person_id: UUID | None = None
    row_id: UUID | None = None
    metadata: dict[str, Any]
    created_at: datetime


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
    uploader: RosterUploaderResponse | None = None
    audit_events: list[RosterAuditEventResponse] = Field(default_factory=list)
    confirmed_at: datetime | None = None
    completed_at: datetime | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    parsed_at: datetime | None = None
    created_at: datetime


class RosterImportListQueryParams(PageParams):
    state: OrganizationRosterImportState | None = None
    roster_type: OrganizationRosterType | None = None


class RosterImportSummaryResponse(BaseModel):
    import_id: UUID
    roster_type: OrganizationRosterType
    source_format: str
    original_filename: str
    state: OrganizationRosterImportState
    counts: RosterPreviewCountsResponse
    uploader: RosterUploaderResponse
    parsed_at: datetime | None = None
    confirmed_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class RosterImportListResponse(BaseModel):
    items: list[RosterImportSummaryResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
    offset: int
    limit: int


class RosterRowListQueryParams(PageParams):
    disposition: OrganizationRosterRowDisposition | None = None
    application_status: OrganizationRosterRowApplicationStatus | None = None


class RosterRowListResponse(BaseModel):
    items: list[RosterPreviewRowResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
    offset: int
    limit: int


class OrganizationRosterListQueryParams(PageParams):
    search: str | None = Field(default=None, max_length=255)


class OrganizationRosterPersonResponse(BaseModel):
    organization_person_id: UUID
    roster_type: OrganizationRosterType
    full_name: str
    email: str | None = None
    phone: str | None = None
    roster_data: dict[str, Any]
    source_status: Literal["organization_provided"] = "organization_provided"
    verified: Literal[False] = False
    source_import_id: UUID | None = None
    source_row_number: int | None = None
    imported_by_user_id: UUID | None = None
    imported_at: datetime


class OrganizationRosterListResponse(BaseModel):
    items: list[OrganizationRosterPersonResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
    offset: int
    limit: int
