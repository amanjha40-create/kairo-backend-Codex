"""DTOs for authenticated Trust Passport share-link management."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PassportSharePermissions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_employments: bool = True
    include_educations: bool = True
    include_internships: bool = True
    include_freelance: bool = True
    include_gig_platforms: bool = True
    include_portfolio: bool = True
    include_certifications: bool = True
    include_skills: bool = False
    include_projects: bool = False
    include_user_documents: bool = False
    show_employer_names: bool = True
    show_documents: bool = False
    show_trust_score: bool = True


class PassportShareCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    label: str | None = Field(default=None, max_length=120)
    expires_at: datetime | None = None
    track_views: bool = True
    permissions: PassportSharePermissions = Field(default_factory=PassportSharePermissions)

    @field_validator("expires_at")
    @classmethod
    def validate_future_expiry(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("expires_at must include timezone information")
        if value <= datetime.now(tz=UTC):
            raise ValueError("expires_at must be in the future")
        return value


class PassportShareUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    label: str | None = Field(default=None, max_length=120)
    expires_at: datetime | None = None
    track_views: bool | None = None
    permissions: PassportSharePermissions | None = None

    @field_validator("expires_at")
    @classmethod
    def validate_future_expiry(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("expires_at must include timezone information")
        if value <= datetime.now(tz=UTC):
            raise ValueError("expires_at must be in the future")
        return value


class PassportShareResponse(BaseModel):
    id: UUID
    label: str | None
    permissions: PassportSharePermissions
    track_views: bool
    expires_at: datetime | None
    revoked_at: datetime | None
    last_viewed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    state: str


class PassportShareCreateResponse(PassportShareResponse):
    share_url: str


class PassportShareRecentViewResponse(BaseModel):
    viewed_at: datetime
    user_agent: str | None
    referrer: str | None
    is_unique_view: bool


class PassportShareAnalyticsResponse(BaseModel):
    share_id: UUID
    total_views: int
    unique_views: int
    last_viewed_at: datetime | None
    recent_views: list[PassportShareRecentViewResponse]
