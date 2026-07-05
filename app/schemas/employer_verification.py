"""Employer confirmation verification — request/response DTOs."""

from __future__ import annotations

import uuid
from datetime import datetime

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

