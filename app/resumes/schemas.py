from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResumeUploadIntentRequest(BaseModel):
    original_filename: str = Field(min_length=1, max_length=512)
    content_type: str
    byte_size: int = Field(gt=0)
    consent_version: str = Field(min_length=1, max_length=64)


class ResumeUploadIntentResponse(BaseModel):
    resume_id: UUID
    upload_url: str
    expires_in: int
    object_key: str


class ResumeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    original_filename: str
    content_type: str
    file_size_bytes: int
    upload_status: str
    processing_status: str
    created_at: datetime
    updated_at: datetime


class ResumeCompleteUploadRequest(BaseModel):
    checksum_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class ResumeProcessResponse(BaseModel):
    resume_id: UUID
    job_id: UUID
    status: str


class ResumeParsedResultResponse(BaseModel):
    resume_id: UUID
    job_id: UUID
    schema_version: str
    status: str
    structured_result: dict[str, Any]
    warnings: list[str]


class LocationClaim(BaseModel):
    city: str | None = None
    region: str | None = None
    country: str | None = None


class ClaimBase(BaseModel):
    model_config = ConfigDict(extra="ignore")
    source_type: Literal["resume"] = "resume"
    source_text_reference: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)
    selected_for_import: bool = False


class EmploymentClaim(ClaimBase):
    company_name: str | None = None
    role_title: str | None = None
    employment_type: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None
    work_arrangement: str | None = None
    location: LocationClaim | None = None
    description: str | None = None


class EducationClaim(ClaimBase):
    institution_name: str | None = None
    degree: str | None = None
    field_of_study: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None
    grade: str | None = None


class InternshipClaim(ClaimBase):
    company_name: str | None = None
    role: str | None = None
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None


class FreelanceClaim(ClaimBase):
    client_name: str | None = None
    project_title: str | None = None
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None


class GigPlatformClaim(ClaimBase):
    platform_name: str | None = None
    partner_role: str | None = None
    partner_id: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None


class CertificationClaim(ClaimBase):
    title: str | None = None
    issuing_organization: str | None = None
    issued_date: date | None = None
    expiry_date: date | None = None
    credential_id: str | None = None
    credential_url: str | None = None


class ProjectClaim(ClaimBase):
    title: str | None = None
    description: str | None = None
    url: str | None = None


class SkillClaim(ClaimBase):
    name: str | None = None


class CandidateResumeProfile(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: LocationClaim | None = None
    professional_headline: str | None = None
    summary: str | None = None
    profile_links: list[str] = Field(default_factory=list)


class ParsedResumeResult(BaseModel):
    schema_version: str = "1"
    candidate_profile: CandidateResumeProfile = Field(default_factory=CandidateResumeProfile)
    employments: list[EmploymentClaim] = Field(default_factory=list)
    education: list[EducationClaim] = Field(default_factory=list)
    internships: list[InternshipClaim] = Field(default_factory=list)
    freelance: list[FreelanceClaim] = Field(default_factory=list)
    gig_platforms: list[GigPlatformClaim] = Field(default_factory=list)
    certifications: list[CertificationClaim] = Field(default_factory=list)
    projects: list[ProjectClaim] = Field(default_factory=list)
    skills: list[SkillClaim] = Field(default_factory=list)
    portfolio_links: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("employments")
    @classmethod
    def validate_employment_dates(cls, values: list[EmploymentClaim]) -> list[EmploymentClaim]:
        for item in values:
            if item.start_date and item.end_date and item.end_date < item.start_date:
                item.warnings.append("end_date_before_start_date")
            if item.is_current and item.end_date:
                item.warnings.append("current_claim_has_end_date")
        return values
