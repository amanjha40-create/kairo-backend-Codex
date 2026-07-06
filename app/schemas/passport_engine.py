"""Canonical backend-owned Trust Passport aggregation DTOs."""

from __future__ import annotations

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


class OwnerPassportResponse(BaseModel):
    profile: UserPublic
    trust_score: TrustScoreResponse
    vault: PublicPassportVault
    passport_metadata: PassportMetadata
    sharing_summary: PassportSharingSummary
    verification_summary: PassportVerificationSummary
