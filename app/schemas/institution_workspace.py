"""Institution workspace dashboards and verification projections.

These contracts intentionally expose only institution-owned academic data and
explicitly consented professional fields. They are not Passport responses.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.institution_people.enums import (
    InstitutionCredentialStatus,
    InstitutionPersonLifecycleStatus,
    InstitutionProfessionalField,
    InstitutionVerificationStatus,
)
from app.schemas.institution_people import InstitutionPeriod, InstitutionProfessionalFieldValue
from app.schemas.pagination import Page, PageParams
from app.verification_requests.enums import VerificationRequestStatus, VerificationRequestType


class InstitutionVerificationInboxQuery(PageParams):
    """Filters for the academic verification inbox."""

    model_config = ConfigDict(str_strip_whitespace=True)

    search: str | None = Field(default=None, max_length=255)
    status: str | None = Field(default=None, max_length=255)
    priority: Literal["low", "normal", "high", "urgent"] | None = None
    request_type: VerificationRequestType | None = None
    assigned_to_me: bool | None = None
    sort_by: Literal["created_at", "updated_at", "due_date", "priority", "status"] = "created_at"
    sort_order: Literal["asc", "desc"] = "desc"

    @field_validator("status")
    @classmethod
    def normalize_statuses(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = ",".join(part.strip() for part in value.split(",") if part.strip())
        return normalized or None

    @property
    def statuses(self) -> set[str]:
        return set(self.status.split(",")) if self.status else set()


class InstitutionVerificationInboxItem(BaseModel):
    public_id: UUID
    subject_name: str
    request_type: VerificationRequestType
    status: VerificationRequestStatus
    priority: Literal["low", "normal", "high", "urgent"]
    due_date: date | None = None
    created_at: datetime
    updated_at: datetime
    assigned_reviewer_name: str | None = None
    education_institution_name: str | None = None
    education_degree: str | None = None


class InstitutionVerificationInboxResponse(Page[InstitutionVerificationInboxItem]):
    pass


class InstitutionComparisonField(BaseModel):
    key: str
    candidate_value: str | None = None
    institution_value: str | None = None
    outcome: Literal["match", "different", "unavailable"]


class InstitutionCandidateEducationClaim(BaseModel):
    institution_name: str | None = None
    degree: str | None = None
    programme: str | None = None
    admission: InstitutionPeriod = Field(default_factory=InstitutionPeriod)
    graduation: InstitutionPeriod = Field(default_factory=InstitutionPeriod)


class InstitutionAuthoritativeRecord(BaseModel):
    found: bool
    student_id: str | None = None
    degree: str | None = None
    programme: str | None = None
    department: str | None = None
    admission: InstitutionPeriod = Field(default_factory=InstitutionPeriod)
    graduation: InstitutionPeriod = Field(default_factory=InstitutionPeriod)
    verification_status: InstitutionVerificationStatus | None = None


class InstitutionVerificationComparison(BaseModel):
    match_status: Literal["exact", "partial", "no_match", "record_unavailable"]
    candidate_claim: InstitutionCandidateEducationClaim
    institution_record: InstitutionAuthoritativeRecord
    fields: list[InstitutionComparisonField] = Field(default_factory=list)


class InstitutionVerificationDetailResponse(InstitutionVerificationInboxItem):
    organization_internal_note: str | None = None
    candidate_response: str | None = None
    candidate_response_submitted_at: datetime | None = None
    consented_fields: list[str] = Field(default_factory=list)
    consented_evidence_scope: list[str] = Field(default_factory=list)
    comparison: InstitutionVerificationComparison


class InstitutionDashboardActivity(BaseModel):
    request_public_id: UUID
    event_type: str
    event_source: str
    created_at: datetime


class InstitutionDashboardCredential(BaseModel):
    public_id: UUID
    title: str
    credential_type: str
    status: InstitutionCredentialStatus
    updated_at: datetime


class InstitutionPeopleSummary(BaseModel):
    total: int = 0
    current_student: int = 0
    alumni: int = 0
    withdrawn: int = 0
    inactive: int = 0


class InstitutionDashboardStatistics(BaseModel):
    total_verifications: int = 0
    verified_verifications: int = 0
    awaiting_information: int = 0
    high_priority: int = 0


class InstitutionDashboardResponse(BaseModel):
    pending_verifications: int = 0
    recently_verified_credentials: list[InstitutionDashboardCredential] = Field(
        default_factory=list
    )
    verification_activity: list[InstitutionDashboardActivity] = Field(default_factory=list)
    people: InstitutionPeopleSummary = Field(default_factory=InstitutionPeopleSummary)
    statistics: InstitutionDashboardStatistics = Field(
        default_factory=InstitutionDashboardStatistics
    )


class InstitutionPassportCredentialSummary(BaseModel):
    public_id: UUID
    title: str
    credential_type: str
    status: InstitutionCredentialStatus
    issued: InstitutionPeriod = Field(default_factory=InstitutionPeriod)


class InstitutionPassportSummaryResponse(BaseModel):
    """A consent-limited institution view, never a full Trust Passport."""

    person_public_id: UUID
    display_name: str
    lifecycle_status: InstitutionPersonLifecycleStatus
    degree: str | None = None
    programme: str | None = None
    department: str | None = None
    admission: InstitutionPeriod = Field(default_factory=InstitutionPeriod)
    graduation: InstitutionPeriod = Field(default_factory=InstitutionPeriod)
    verification_status: InstitutionVerificationStatus
    consented_professional_fields: list[InstitutionProfessionalField] = Field(default_factory=list)
    professional_information: list[InstitutionProfessionalFieldValue] = Field(default_factory=list)
    credentials: list[InstitutionPassportCredentialSummary] = Field(default_factory=list)
