"""Canonical backend-owned Trust Passport, dashboard, and onboarding DTOs."""

from __future__ import annotations

from typing import Literal
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.public_passport import PublicPassportVault
from app.schemas.trust_score import TrustScoreResponse
from app.schemas.user import UserPublic


class PassportSectionStatusSummary(BaseModel):
    total: int
    statuses: dict[str, int]


class PassportVerificationSummary(BaseModel):
    overall: PassportSectionStatusSummary
    employments: PassportSectionStatusSummary
    educations: PassportSectionStatusSummary
    internships: PassportSectionStatusSummary
    freelance: PassportSectionStatusSummary
    gig_platforms: PassportSectionStatusSummary
    portfolio: PassportSectionStatusSummary
    certifications: PassportSectionStatusSummary
    user_documents: PassportSectionStatusSummary


class PassportMetadata(BaseModel):
    owner_user_id: UUID
    profile_slug: str | None
    is_email_verified: bool
    is_onboarding_complete: bool
    created_at: datetime
    updated_at: datetime
    employment_onboarding_completed_at: datetime | None


class PassportSharingSummary(BaseModel):
    total_links: int
    active_links: int
    revoked_links: int
    expired_links: int
    total_views: int
    unique_views: int
    latest_share_created_at: datetime | None
    last_viewed_at: datetime | None


class OnboardingStatusResponse(BaseModel):
    current_step: Literal["verify_identity", "complete_profile", "complete"]
    email_verified: bool
    phone_verified: bool
    passport_ready: bool
    completed_steps: list[str]
    missing_requirements: list[str]
    next_recommended_step: str | None
    completion_percentage: int
    is_onboarding_complete: bool


class DashboardVaultSummary(BaseModel):
    total_items: int
    employments: int
    educations: int
    internships: int
    freelance: int
    gig_platforms: int
    portfolio: int
    certifications: int
    user_documents: int


class DashboardShareSummaryItem(BaseModel):
    share_id: UUID
    label: str | None
    state: str
    expires_at: datetime | None
    last_viewed_at: datetime | None
    created_at: datetime


class DashboardActivePassportShares(BaseModel):
    count: int
    items: list[DashboardShareSummaryItem]


class DashboardShareAnalyticsItem(BaseModel):
    share_id: UUID
    label: str | None
    state: str
    total_views: int
    unique_views: int
    last_viewed_at: datetime | None


class DashboardActivityItem(BaseModel):
    occurred_at: datetime
    category: Literal["verification", "passport_share"]
    action: str
    title: str
    detail: str | None
    subject_id: UUID | None


class DashboardResponse(BaseModel):
    profile_completion: OnboardingStatusResponse
    profile_completion_percentage: int = 0
    trust_score: TrustScoreResponse
    verification_summary: PassportVerificationSummary
    vault_summary: DashboardVaultSummary
    active_passport_shares: DashboardActivePassportShares
    recent_share_analytics: list[DashboardShareAnalyticsItem]
    recent_activity: list[DashboardActivityItem]


class OwnerPassportResponse(BaseModel):
    profile: UserPublic
    trust_score: TrustScoreResponse
    vault: PublicPassportVault
    passport_metadata: PassportMetadata
    sharing_summary: PassportSharingSummary
    verification_summary: PassportVerificationSummary
