"""Employer confirmation verification — request/response DTOs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.employment.enums import EmployerVerificationDecision


class EmployerVerificationRequestBody(BaseModel):
    """Ask an employer contact to confirm employment via email magic links."""

    model_config = ConfigDict(str_strip_whitespace=True)

    contact_name: str = Field(..., min_length=1, max_length=255)
    verifier_email: EmailStr
    relationship: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Verifier relationship to the subject (e.g. manager, HR)",
    )


class EmployerVerificationRequestResponse(BaseModel):
    message: str = "Verification email sent to the employer contact"
    employment_id: uuid.UUID
    verifier_email_masked: str
    expires_at: datetime


class EmployerVerificationStatusResponse(BaseModel):
    """Current outbound employer request state (applicant detail view)."""

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    contact_name: str
    verifier_email_masked: str
    relationship: str
    response: EmployerVerificationDecision
    sent_at: datetime
    expires_at: datetime
    responded_at: datetime | None = None


class AdminEmployerVerificationSummary(BaseModel):
    public_id: uuid.UUID
    status: EmployerVerificationDecision
    masked_recipient: str
    delivery_status: str
    created_at: datetime
    updated_at: datetime


class AdminEmployerVerificationResponse(BaseModel):
    employer_verification: AdminEmployerVerificationSummary


class EmployerPortalCandidate(BaseModel):
    full_name: str


class EmployerPortalEmployment(BaseModel):
    employer_name: str
    job_title: str
    employment_type: str
    start_date: str
    end_date: str | None = None
    country: str
    region: str | None = None


class EmployerPortalEvidence(BaseModel):
    document_type: str
    original_filename: str
    mime_type: str
    file_size: int
    status: str


class EmployerPortalTimelineEvent(BaseModel):
    event_type: str
    previous_status: str | None = None
    new_status: str | None = None
    created_at: datetime


class EmployerPortalContact(BaseModel):
    contact_name: str
    relationship: str
    email_masked: str


class EmployerPortalWorkspace(BaseModel):
    employer_verification_public_id: uuid.UUID
    state: Literal["pending", "completed"]
    decision: EmployerVerificationDecision | None = None
    expires_at: datetime
    candidate: EmployerPortalCandidate
    employment: EmployerPortalEmployment
    evidence_summary: list[EmployerPortalEvidence]
    verification_request_public_id: uuid.UUID | None = None
    verification_request_status: str | None = None
    employer_contact: EmployerPortalContact
    timeline: list[EmployerPortalTimelineEvent]


class EmployerVerifyBody(BaseModel):
    employment_existed: bool
    dates_correct: bool
    role_correct: bool
    comments: str | None = Field(default=None, max_length=4000)


class EmployerDecisionBody(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)
    comments: str | None = Field(default=None, max_length=4000)


class EmployerPortalActionResponse(BaseModel):
    employer_verification_public_id: uuid.UUID
    decision: EmployerVerificationDecision
    verification_request_status: str | None = None
    employment_verification_status: str
    idempotent: bool = False
