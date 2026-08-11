"""Read-only directory DTOs used by Admin operational workflows."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.pagination import Page


class AdminReviewerResponse(BaseModel):
    user_id: UUID
    full_name: str | None
    email: str
    role: str


class AdminOrganizationSearchItem(BaseModel):
    public_id: UUID
    name: str
    organization_type: str
    verification_capabilities: list[str]
    registry_record_public_id: UUID | None
    registry_resolution_status: str


class AdminUserDirectoryItem(BaseModel):
    public_id: UUID
    display_name: str
    masked_email: str
    account_status: str
    created_at: datetime
    last_relevant_activity_at: datetime | None = None
    profile_completion_percentage: int = 0
    trust_score_overall: int | None = None
    trust_score_status: str | None = None
    active_verification_count: int = 0
    completed_verification_count: int = 0
    career_record_count: int = 0
    active_passport_share_count: int = 0
    deleted_at: datetime | None = None


class AdminUserTrustSummary(BaseModel):
    overall: int | None = None
    status: str | None = None
    verification_completeness_percentage: int = 0
    last_calculated_at: datetime | None = None


class AdminUserCareerSummary(BaseModel):
    total_items: int = 0
    employments: int = 0
    educations: int = 0
    internships: int = 0
    freelance: int = 0
    gig_platforms: int = 0
    portfolio: int = 0
    certifications: int = 0
    skills: int = 0
    projects: int = 0
    user_documents: int = 0


class AdminUserVerificationBreakdown(BaseModel):
    total: int = 0
    statuses: dict[str, int] = Field(default_factory=dict)


class AdminUserVerificationSummary(BaseModel):
    overall: AdminUserVerificationBreakdown = Field(default_factory=AdminUserVerificationBreakdown)
    employments: AdminUserVerificationBreakdown = Field(
        default_factory=AdminUserVerificationBreakdown
    )
    educations: AdminUserVerificationBreakdown = Field(
        default_factory=AdminUserVerificationBreakdown
    )
    certifications: AdminUserVerificationBreakdown = Field(
        default_factory=AdminUserVerificationBreakdown
    )


class AdminUserVerificationItem(BaseModel):
    public_id: UUID
    request_type: str
    status: str
    employment_public_id: UUID | None = None
    education_public_id: UUID | None = None
    organization_public_id: UUID | None = None
    organization_name: str | None = None
    linked_record_label: str
    created_at: datetime
    submitted_at: datetime | None = None
    updated_at: datetime


class AdminUserPassportSummary(BaseModel):
    ready: bool
    active_links: int = 0
    revoked_links: int = 0
    expired_links: int = 0
    total_views: int = 0
    unique_views: int = 0
    latest_share_created_at: datetime | None = None
    last_viewed_at: datetime | None = None


class AdminUserActivityEvent(BaseModel):
    public_id: UUID
    occurred_at: datetime
    kind: str
    title: str
    detail: str | None = None


class AdminUserDetailResponse(BaseModel):
    public_id: UUID
    display_name: str
    account_status: str
    email: str
    masked_email: str
    phone: str | None = None
    masked_phone: str | None = None
    headline: str | None = None
    current_role: str | None = None
    location: str | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    email_verified: bool = False
    phone_verified: bool = False
    onboarding_completed: bool = False
    profile_completion_percentage: int = 0
    trust: AdminUserTrustSummary = Field(default_factory=AdminUserTrustSummary)
    career_summary: AdminUserCareerSummary = Field(default_factory=AdminUserCareerSummary)
    verification_summary: AdminUserVerificationSummary = Field(
        default_factory=AdminUserVerificationSummary
    )
    verifications: list[AdminUserVerificationItem] = Field(default_factory=list)
    passport: AdminUserPassportSummary
    activity: list[AdminUserActivityEvent] = Field(default_factory=list)


class AdminReviewerPage(Page[AdminReviewerResponse]):
    pass


class AdminOrganizationSearchPage(Page[AdminOrganizationSearchItem]):
    pass


class AdminUserPage(Page[AdminUserDirectoryItem]):
    pass
