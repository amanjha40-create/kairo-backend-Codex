"""Public institution magic-link verification contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PublicInstitutionVerificationState = Literal["valid", "expired", "completed", "revoked", "invalid"]


class PublicInstitutionVerificationCandidateClaim(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    candidate_name: str = Field(min_length=1, max_length=255)
    student_id: str | None = Field(default=None, max_length=128)
    institution_name: str = Field(min_length=1, max_length=255)
    degree: str = Field(min_length=1, max_length=255)
    programme: str = Field(min_length=1, max_length=255)
    department: str = Field(min_length=1, max_length=255)
    admission_year: str = Field(min_length=1, max_length=64)
    graduation_year: str = Field(min_length=1, max_length=64)
    completion_status: str = Field(min_length=1, max_length=128)
    additional_note: str | None = Field(default=None, max_length=2000)


class PublicInstitutionVerificationEvidenceFile(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    type: str = Field(min_length=1, max_length=128)
    uploaded_by: str = Field(min_length=1, max_length=255)
    uploaded_at: datetime
    url: str | None = Field(default=None, max_length=4096)


class PublicInstitutionVerificationRequestProjection(BaseModel):
    reference: str = Field(min_length=1, max_length=64)
    requested_by: str = Field(min_length=1, max_length=255)
    purpose: str = Field(min_length=1, max_length=255)
    request_date: datetime
    consent_received: bool
    candidate: PublicInstitutionVerificationCandidateClaim
    evidence: list[PublicInstitutionVerificationEvidenceFile] = Field(default_factory=list)


class PublicInstitutionVerificationReadResponse(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    state: PublicInstitutionVerificationState
    expires_at: datetime | None = None
    request: PublicInstitutionVerificationRequestProjection | None = None


class PublicInstitutionVerificationConfirmRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    note: str | None = Field(default=None, max_length=2000)


class PublicInstitutionVerificationDiscrepancyRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    fields: list[str] = Field(min_length=1, max_length=50)
    explanation: str = Field(min_length=3, max_length=2000)


class PublicInstitutionVerificationClarificationRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    fields: list[str] = Field(min_length=1, max_length=50)
    message: str = Field(min_length=3, max_length=2000)
    request_document: bool = False
