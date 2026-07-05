"""Generic credential confirmation verification — request/response DTOs."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class CredentialVerificationRequestBody(BaseModel):
    """Ask a verifier contact to confirm an internship / freelance engagement via email."""

    model_config = ConfigDict(str_strip_whitespace=True)

    contact_name: str = Field(..., min_length=1, max_length=255)
    verifier_email: EmailStr
    relationship: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Verifier relationship to the subject (e.g. manager, client)",
    )


class CredentialVerificationRequestResponse(BaseModel):
    message: str = "Verification email sent to the contact"
    subject_id: uuid.UUID
    verifier_email_masked: str
    expires_at: datetime
