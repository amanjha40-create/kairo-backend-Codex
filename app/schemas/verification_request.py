"""Verification request engine DTOs."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.verification_requests.enums import (
    VerificationRequestEventSource,
    VerificationRequestStatus,
    VerificationRequestType,
)


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


class VerificationRequestResponse(BaseModel):
    public_id: UUID
    organization_public_id: UUID
    trust_invitation_public_id: UUID | None
    subject_name: str
    subject_email: EmailStr
    request_type: VerificationRequestType
    status: VerificationRequestStatus
    due_date: date | None
    trust_context: dict[str, Any]
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
