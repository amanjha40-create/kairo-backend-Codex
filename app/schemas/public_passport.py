"""Public Trust Passport response DTOs."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.passport_share import PassportSharePermissions
from app.schemas.trust_score import TrustScoreResponse


class PublicPassportProfile(BaseModel):
    full_name: str | None
    headline: str | None
    location: str | None
    avatar_url: str | None
    profile_slug: str | None


class PublicPassportDocument(BaseModel):
    id: uuid.UUID
    document_type: str
    original_filename: str
    byte_size: int
    verification_status: str


class PublicPassportEmployment(BaseModel):
    id: uuid.UUID
    employer_legal_name: str | None
    job_title: str
    start_date: date
    end_date: date | None
    verification_status: str
    verification_method: str
    documents: list[PublicPassportDocument]


class PublicPassportEducation(BaseModel):
    id: uuid.UUID
    institution_name: str
    degree: str
    field_of_study: str | None
    education_level: str
    grade: str | None
    start_date: date
    end_date: date | None
    is_currently_studying: bool
    verification_status: str


class PublicPassportInternship(BaseModel):
    id: uuid.UUID
    company_name: str
    role: str
    description: str | None
    start_date: date
    end_date: date | None
    is_ongoing: bool
    verification_status: str


class PublicPassportFreelance(BaseModel):
    id: uuid.UUID
    client_name: str
    project_title: str
    description: str | None
    start_date: date
    end_date: date | None
    is_ongoing: bool
    verification_status: str


class PublicPassportGigPlatform(BaseModel):
    id: uuid.UUID
    platform_name: str
    partner_role: str
    started_at: date
    ended_at: date | None
    is_active: bool
    rating: float | None
    verification_status: str


class PublicPassportPortfolioItem(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    url: str | None
    tags: list[str]
    verification_status: str


class PublicPassportCertification(BaseModel):
    id: uuid.UUID
    title: str
    issuing_organization: str
    issued_date: date
    expiry_date: date | None
    does_not_expire: bool
    credential_id: str | None
    credential_url: str | None
    verification_status: str


class PublicPassportSkill(BaseModel):
    name: str
    verification_status: str


class PublicPassportProject(BaseModel):
    id: uuid.UUID
    title: str
    role: str | None
    description: str | None
    start_date: date | None
    end_date: date | None
    is_ongoing: bool
    project_url: str | None
    repository_url: str | None
    organization_name: str | None
    verification_status: str


class PublicPassportUserDocument(BaseModel):
    id: uuid.UUID
    document_type: str
    original_filename: str
    byte_size: int
    verification_status: str
    expires_at: date | None


class PublicPassportVault(BaseModel):
    employments: list[PublicPassportEmployment]
    educations: list[PublicPassportEducation]
    internships: list[PublicPassportInternship]
    freelance: list[PublicPassportFreelance]
    gig_platforms: list[PublicPassportGigPlatform]
    portfolio: list[PublicPassportPortfolioItem]
    certifications: list[PublicPassportCertification]
    skills: list[PublicPassportSkill] = Field(default_factory=list)
    projects: list[PublicPassportProject] = Field(default_factory=list)
    user_documents: list[PublicPassportUserDocument]


class PublicPassportShareMetadata(BaseModel):
    id: uuid.UUID
    label: str | None
    expires_at: datetime | None
    track_views: bool
    permissions: PassportSharePermissions


class PublicPassportResponse(BaseModel):
    profile: PublicPassportProfile
    trust_score: TrustScoreResponse | None
    vault: PublicPassportVault
    share: PublicPassportShareMetadata
