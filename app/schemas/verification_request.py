"""Verification request engine DTOs."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.admin_review.enums import VerificationRequestEvidenceStatus, VerificationReviewCorrectionStatus
from app.verification_requests.enums import (
    VerificationContactReviewStatus,
    VerificationContactType,
    VerificationRequestEventSource,
    VerificationRequestOriginType,
    VerificationRequestStatus,
    VerificationRequestType,
)


class VerificationContactRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    contact_name: str | None = Field(default=None, max_length=255)
    contact_email: EmailStr
    contact_role: str | None = Field(default=None, max_length=128)
    contact_type: VerificationContactType
    candidate_note: str | None = Field(default=None, max_length=2000)


class VerificationContactResponse(BaseModel):
    public_id: UUID
    contact_name: str | None
    contact_email: EmailStr
    contact_role: str | None
    contact_type: VerificationContactType
    candidate_note: str | None
    review_status: VerificationContactReviewStatus
    review_notes: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class EmploymentVerificationDraftRequest(BaseModel):
    verification_contact: VerificationContactRequest
    employment_document_ids: list[UUID] = Field(min_length=1, max_length=20)


class VerificationRequestCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    subject_name: str | None = Field(default=None, min_length=1, max_length=255)
    subject_email: EmailStr | None = None
    trust_invitation_public_id: UUID | None = None
    request_type: VerificationRequestType
    due_date: date | None = None
    trust_context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_subject_source(self) -> "VerificationRequestCreateRequest":
        has_direct_subject = self.subject_name is not None and self.subject_email is not None
        if self.trust_invitation_public_id is None and not has_direct_subject:
            raise ValueError("Provide subject_name and subject_email, or trust_invitation_public_id")
        return self


class VerificationRequestActionPayload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    note: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubjectVerificationRequestCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    organization_public_id: UUID | None = None
    target_organization_name: str | None = Field(default=None, min_length=1, max_length=255)
    target_organization_email: EmailStr | None = None
    request_type: VerificationRequestType
    due_date: date | None = None
    trust_context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_target(self) -> "SubjectVerificationRequestCreateRequest":
        if (
            self.organization_public_id is None
            and self.target_organization_name is None
            and self.target_organization_email is None
        ):
            raise ValueError("Provide organization_public_id or target organization details")
        return self


class VerificationRequestEvidenceCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    evidence_type: str = Field(min_length=1, max_length=64)
    field_key: str = Field(min_length=1, max_length=128)
    document_id: UUID | None = None
    employment_document_id: UUID | None = None
    value: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> "VerificationRequestEvidenceCreateRequest":
        supplied_documents = sum(item is not None for item in (self.document_id, self.employment_document_id))
        if supplied_documents > 1:
            raise ValueError("Provide only one document reference")
        if supplied_documents == 0 and self.value is None:
            raise ValueError("Provide a document reference or value")
        return self


class VerificationRequestEvidenceUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    evidence_type: str | None = Field(default=None, min_length=1, max_length=64)
    field_key: str | None = Field(default=None, min_length=1, max_length=128)
    document_id: UUID | None = None
    employment_document_id: UUID | None = None
    value: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> "VerificationRequestEvidenceUpdateRequest":
        if self.document_id is not None and self.employment_document_id is not None:
            raise ValueError("Provide only one document reference")
        if (
            self.evidence_type is None
            and self.field_key is None
            and self.document_id is None
            and self.employment_document_id is None
            and self.value is None
        ):
            raise ValueError("Provide at least one field to update")
        return self


class VerificationRequestResponse(BaseModel):
    public_id: UUID
    employment_id: UUID | None = None
    origin_type: VerificationRequestOriginType | None = None
    organization_public_id: UUID | None = None
    trust_invitation_public_id: UUID | None
    subject_name: str
    subject_email: EmailStr
    target_organization_name: str | None = None
    target_organization_email: EmailStr | None = None
    request_type: VerificationRequestType
    status: VerificationRequestStatus
    due_date: date | None
    trust_context: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class VerificationRequestEvidenceResponse(BaseModel):
    public_id: UUID
    evidence_type: str
    field_key: str
    document_id: UUID | None
    employment_document_id: UUID | None = None
    value: dict[str, Any] | None
    status: VerificationRequestEvidenceStatus
    created_at: datetime
    updated_at: datetime


class VerificationRequestCorrectionResponse(BaseModel):
    public_id: UUID
    evidence_public_id: UUID | None
    field_key: str
    request_text: str
    guidance: dict[str, Any]
    status: VerificationReviewCorrectionStatus
    created_at: datetime
    updated_at: datetime


class VerificationRequestTimelineEventResponse(BaseModel):
    public_id: UUID
    event_type: str
    event_source: VerificationRequestEventSource
    previous_status: VerificationRequestStatus | None
    new_status: VerificationRequestStatus | None
    metadata: dict[str, Any]
    created_at: datetime


class VerificationRequestTimelineResponse(BaseModel):
    verification_request_public_id: UUID
    items: list[VerificationRequestTimelineEventResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
    offset: int
    limit: int
