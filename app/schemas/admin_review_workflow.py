"""Admin review workflow DTOs for verification requests."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.admin_review.enums import (
    VerificationRequestReviewStatus,
    VerificationReviewNoteType,
    VerificationReviewNoteVisibility,
)
from app.schemas.verification_request import (
    VerificationRequestCorrectionResponse,
    VerificationRequestEvidenceResponse,
    VerificationRequestResponse,
    VerificationRequestTimelineResponse,
)
from app.schemas.employment.responses import EmploymentResponse
from app.verification_requests.enums import VerificationContactReviewStatus


class AdminVerificationContactReviewRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    review_status: VerificationContactReviewStatus
    review_notes: str | None = Field(default=None, max_length=5000)


class AdminReviewerSummary(BaseModel):
    user_id: UUID
    full_name: str | None
    email: str
    role: str


class AdminReviewEvidenceResponse(VerificationRequestEvidenceResponse):
    document_type: str | None = None
    original_filename: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    upload_status: str | None = None


class AdminEvidenceDownloadResponse(BaseModel):
    evidence_public_id: UUID
    download_url: str
    expires_in_seconds: int


class AdminVerificationContactResponse(BaseModel):
    public_id: UUID
    contact_name: str | None
    contact_email: str
    contact_role: str | None
    contact_type: str
    candidate_note: str | None
    review_status: str
    review_notes: str | None
    reviewed_by_user_id: UUID | None
    reviewed_at: datetime | None
    superseded_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AdminOrganizationResolutionResponse(BaseModel):
    status: str
    organization_public_id: UUID | None
    organization_name: str | None


class AdminRegistryResolutionResponse(BaseModel):
    status: str
    registry_record_public_id: UUID | None
    registry_code: str | None
    registry_name: str | None
    resolution_method: str | None
    resolution_confidence: float | None
    resolution_metadata: dict[str, object]


class AdminReviewQueueItemResponse(VerificationRequestResponse):
    model_config = ConfigDict(from_attributes=True)

    assigned_reviewer: AdminReviewerSummary | None = None
    contact_review_status: str | None = None
    organization_resolution_status: str = "unresolved"
    registry_resolution_status: str = "unresolved"


class AdminReviewQueueResponse(BaseModel):
    items: list[AdminReviewQueueItemResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
    offset: int
    limit: int


class AdminReviewAssignRequest(BaseModel):
    assignee_user_id: UUID


class AdminReviewNoteCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    visibility: VerificationReviewNoteVisibility = VerificationReviewNoteVisibility.INTERNAL
    note_type: VerificationReviewNoteType = VerificationReviewNoteType.REVIEW_NOTE
    body: str = Field(min_length=1, max_length=5000)
    metadata: dict[str, object] = Field(default_factory=dict)


class AdminReviewCorrectionItemRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    evidence_public_id: UUID | None = None
    field_key: str = Field(min_length=1, max_length=128)
    request_text: str = Field(min_length=1, max_length=5000)
    guidance: dict[str, object] = Field(default_factory=dict)


class AdminReviewCorrectionRequest(BaseModel):
    corrections: list[AdminReviewCorrectionItemRequest] = Field(min_length=1)


class AdminReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    decision_summary: str = Field(min_length=1, max_length=5000)


class AdminReviewOrganizationResolutionRequest(BaseModel):
    organization_public_id: UUID


class AdminReviewNoteResponse(BaseModel):
    public_id: UUID
    visibility: VerificationReviewNoteVisibility
    note_type: VerificationReviewNoteType
    body: str
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime


class AdminReviewInternalNoteResponse(AdminReviewNoteResponse):
    review_public_id: UUID
    author_user_id: UUID | None


class AdminReviewCycleResponse(BaseModel):
    public_id: UUID
    review_round: int
    review_status: VerificationRequestReviewStatus
    assigned_reviewer_user_id: UUID | None
    assigned_by_user_id: UUID | None
    assigned_at: datetime | None
    decision_by_user_id: UUID | None
    decision_at: datetime | None
    decision_summary: str | None
    created_at: datetime
    updated_at: datetime


class AdminReviewDetailResponse(BaseModel):
    request: VerificationRequestResponse
    employer_verification_public_id: UUID | None = None
    employment: EmploymentResponse | None = None
    verification_contact: AdminVerificationContactResponse | None = None
    verification_contact_history: list[AdminVerificationContactResponse] = Field(default_factory=list)
    evidence: list[AdminReviewEvidenceResponse]
    reviews: list[AdminReviewCycleResponse]
    open_corrections: list[VerificationRequestCorrectionResponse]
    internal_notes: list[AdminReviewInternalNoteResponse] = Field(default_factory=list)
    organization_resolution: AdminOrganizationResolutionResponse = Field(
        default_factory=lambda: AdminOrganizationResolutionResponse(
            status="unresolved",
            organization_public_id=None,
            organization_name=None,
        )
    )
    registry_resolution: AdminRegistryResolutionResponse = Field(
        default_factory=lambda: AdminRegistryResolutionResponse(
            status="unresolved",
            registry_record_public_id=None,
            registry_code=None,
            registry_name=None,
            resolution_method=None,
            resolution_confidence=None,
            resolution_metadata={},
        )
    )


class AdminReviewWorkflowEnvelope(BaseModel):
    request: VerificationRequestResponse
    review: AdminReviewCycleResponse


class AdminReviewTimelineResponse(BaseModel):
    timeline: VerificationRequestTimelineResponse
