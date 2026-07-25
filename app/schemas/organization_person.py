"""Organization People Registry DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.organization_people.enums import (
    OrganizationPersonInvitationStatusSummary,
    OrganizationPersonPassportStatusSummary,
    OrganizationPersonRelationship,
    OrganizationPersonTrustState,
    OrganizationPersonVerificationStatusSummary,
)
from app.schemas.pagination import ListQueryParams


class OrganizationPeopleListQueryParams(ListQueryParams):
    relationship: OrganizationPersonRelationship | None = None
    invitation_status: OrganizationPersonInvitationStatusSummary | None = None
    verification_status: OrganizationPersonVerificationStatusSummary | None = None
    passport_status: OrganizationPersonPassportStatusSummary | None = None
    trust_state: OrganizationPersonTrustState | None = None
    added_by: str | None = None


class OrganizationPersonSummaryCounts(BaseModel):
    invitations: int = 0
    verification_requests: int = 0
    shared_evidence_items: int = 0
    internal_notes: int = 0


class OrganizationPeopleDirectorySummary(BaseModel):
    total_people: int = 0
    by_relationship: dict[str, int] = Field(default_factory=dict)
    by_invitation_status: dict[str, int] = Field(default_factory=dict)
    by_verification_status: dict[str, int] = Field(default_factory=dict)
    by_passport_status: dict[str, int] = Field(default_factory=dict)
    by_trust_state: dict[str, int] = Field(default_factory=dict)


class OrganizationPersonListItemResponse(BaseModel):
    id: UUID
    public_id: UUID
    name: str
    full_name: str
    email: EmailStr | None = None
    phone: str | None = None
    relationship: OrganizationPersonRelationship
    trust_state: OrganizationPersonTrustState
    invitation_status: OrganizationPersonInvitationStatusSummary
    verification_status: OrganizationPersonVerificationStatusSummary
    passport_status: OrganizationPersonPassportStatusSummary
    added_by: str | None = None
    added_at: datetime
    last_activity_at: datetime | None = None
    summary_counts: OrganizationPersonSummaryCounts = Field(default_factory=OrganizationPersonSummaryCounts)


class OrganizationPeopleListResponse(BaseModel):
    items: list[OrganizationPersonListItemResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
    offset: int
    limit: int
    summary: OrganizationPeopleDirectorySummary = Field(default_factory=OrganizationPeopleDirectorySummary)


class OrganizationPersonRelationshipSummaryResponse(BaseModel):
    relationship: OrganizationPersonRelationship
    trust_state: OrganizationPersonTrustState
    invitation_status: OrganizationPersonInvitationStatusSummary
    verification_status: OrganizationPersonVerificationStatusSummary
    passport_status: OrganizationPersonPassportStatusSummary
    added_by: str | None = None
    added_at: datetime
    last_activity_at: datetime | None = None
    resolution_state: str
    resolution_method: str | None = None
    resolution_confidence: float | None = None
    resolution_metadata: dict[str, Any] = Field(default_factory=dict)


class OrganizationPersonPassportClaimResponse(BaseModel):
    label: str
    value: str | None = None
    status: str
    source: str | None = None


class OrganizationPersonPassportPreviewResponse(BaseModel):
    status: OrganizationPersonPassportStatusSummary
    shared_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    permissions: dict[str, bool] = Field(default_factory=dict)
    claims: list[OrganizationPersonPassportClaimResponse] = Field(default_factory=list)


class OrganizationPersonVerificationSummaryResponse(BaseModel):
    latest_status: OrganizationPersonVerificationStatusSummary
    total_requests: int = 0
    completed_requests: int = 0
    active_requests: int = 0
    clarification_required_requests: int = 0


class OrganizationPersonEmploymentVerificationResponse(BaseModel):
    id: UUID
    public_id: UUID
    status: str
    requested_by: str | None = None
    requested_at: datetime
    request_type: str
    request_public_id: UUID


class OrganizationPersonSharedEvidenceResponse(BaseModel):
    id: UUID
    public_id: UUID
    request_public_id: UUID
    type: str
    shared_at: datetime
    status: str
    original_filename: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    download_url: str | None = None
    download_url_expires_in_seconds: int | None = None


class OrganizationPersonActivityResponse(BaseModel):
    id: str
    kind: str
    label: str
    actor: str
    at: datetime
    request_public_id: UUID | None = None
    source_type: str
    source_public_id: str | None = None


class OrganizationPersonNoteResponse(BaseModel):
    id: UUID
    public_id: UUID
    author: str | None = None
    author_user_id: UUID | None = None
    body: str
    at: datetime
    created_at: datetime
    updated_at: datetime
    owned_by_current_user: bool = False


class OrganizationPersonSummaryResponse(BaseModel):
    full_name: str
    email: EmailStr | None = None
    phone: str | None = None
    linked_user_id: UUID | None = None


class OrganizationPersonDetailResponse(BaseModel):
    id: UUID
    public_id: UUID
    summary: OrganizationPersonSummaryResponse
    passport_preview: OrganizationPersonPassportPreviewResponse
    verification_summary: OrganizationPersonVerificationSummaryResponse
    employment_verifications: list[OrganizationPersonEmploymentVerificationResponse] = Field(default_factory=list)
    shared_evidence: list[OrganizationPersonSharedEvidenceResponse] = Field(default_factory=list)
    activity: list[OrganizationPersonActivityResponse] = Field(default_factory=list)
    internal_notes: list[OrganizationPersonNoteResponse] = Field(default_factory=list)
    organization_relationship: OrganizationPersonRelationshipSummaryResponse


class OrganizationPersonNoteRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    body: str = Field(min_length=1, max_length=5000)
