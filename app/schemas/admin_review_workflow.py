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
from app.verification_requests.enums import VerificationContactReviewStatus


class AdminVerificationContactReviewRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    review_status: VerificationContactReviewStatus
    review_notes: str | None = Field(default=None, max_length=5000)


class AdminReviewQueueResponse(BaseModel):
    items: list[VerificationRequestResponse]
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
    evidence: list[VerificationRequestEvidenceResponse]
    reviews: list[AdminReviewCycleResponse]
    open_corrections: list[VerificationRequestCorrectionResponse]


class AdminReviewWorkflowEnvelope(BaseModel):
    request: VerificationRequestResponse
    review: AdminReviewCycleResponse


class AdminReviewTimelineResponse(BaseModel):
    timeline: VerificationRequestTimelineResponse
