"""Explicit Admin read DTOs; never serialize ORM/provider objects."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.permanent_address import ManualLocationDetail, PermanentAddressInput


class AdminAddressSummary(BaseModel):
    candidate_id: UUID
    address_version_id: UUID | None
    address_version: int | None
    overall_status: str
    document_status: str
    successful_location_checks: int
    required_location_checks: Literal[3] = 3
    today_complete: bool
    separate_days_required: Literal[True] = True
    cycle_expires_at: datetime | None
    manual_review_status: str | None
    pending_manual_review_target_available: bool
    manual_location_approval_eligible: bool
    active_target_source: (
        Literal["provider_geocode", "onsite_confirmation", "onsite_confirmation_manual_review"]
        | None
    )
    current_attempt_state: str | None


class AdminAddressDiscovery(BaseModel):
    items: list[AdminAddressSummary]
    next_offset: int | None


class AdminAddressVersion(BaseModel):
    address_version_id: UUID
    address_version: int
    current: bool
    created_at: datetime
    invalidated_at: datetime | None


class AdminAddressDocument(BaseModel):
    present: bool = False
    document_id: UUID | None = None
    document_type: str | None = None
    upload_state: str | None = None
    review_state: str = "REQUIRED"
    uploaded_at: datetime | None = None
    issued_on: date | None = None
    reviewed_at: datetime | None = None
    preview_available: bool = False
    content_path: str | None = None


class AdminAddressEvent(BaseModel):
    action: str
    at: datetime


class AdminAddressDetail(BaseModel):
    permanent_address: AdminAddressSummary
    claimed_address: PermanentAddressInput | None
    document: AdminAddressDocument
    latest_attempt: ManualLocationDetail | None = None
    versions: list[AdminAddressVersion] = Field(default_factory=list)
    audit: list[AdminAddressEvent] = Field(default_factory=list)
