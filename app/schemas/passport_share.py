"""DTOs for authenticated Trust Passport share-link management."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

SharingMode = Literal["verified_only", "verified_and_candidate_provided"]
ResolvedSharingMode = Literal["legacy_mixed", "verified_only", "verified_and_candidate_provided"]


class PassportSharePermissions(BaseModel):
    """Frozen legacy defaults; never use these defaults when creating V2 shares."""
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
    include_profile: bool = True
    show_photo: bool = True


class PassportShareV2Permissions(PassportSharePermissions):
    model_config = ConfigDict(extra="forbid", strict=True)

    include_internships: bool = False
    include_freelance: bool = False
    include_gig_platforms: bool = False
    include_portfolio: bool = False
    include_certifications: bool = False
    show_trust_score: bool = False
    include_profile: bool = False
    show_photo: bool = False


class PassportSharePermissionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_employments: StrictBool | None = None
    include_educations: StrictBool | None = None
    include_internships: StrictBool | None = None
    include_freelance: StrictBool | None = None
    include_gig_platforms: StrictBool | None = None
    include_portfolio: StrictBool | None = None
    include_certifications: StrictBool | None = None
    include_skills: StrictBool | None = None
    include_projects: StrictBool | None = None
    include_user_documents: StrictBool | None = None
    show_employer_names: StrictBool | None = None
    show_documents: StrictBool | None = None
    show_trust_score: StrictBool | None = None
    include_profile: StrictBool | None = None
    show_photo: StrictBool | None = None

    @model_validator(mode="after")
    def no_explicit_null(self):
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Permission values must be booleans")
        return self


VERIFIED_SECTIONS = ("include_employments", "include_educations")
MIXED_SECTIONS = (*VERIFIED_SECTIONS, "include_certifications", "include_skills", "include_projects", "include_user_documents", "include_profile", "show_photo")
LEGACY_ONLY_SECTIONS = ("include_portfolio", "include_internships", "include_freelance", "include_gig_platforms")


def validate_v2_permissions(mode: SharingMode, permissions: PassportSharePermissions) -> None:
    if any(getattr(permissions, key) for key in LEGACY_ONLY_SECTIONS):
        raise ValueError("This category is available only on legacy shares")
    if mode == "verified_only" and any(getattr(permissions, key) for key in MIXED_SECTIONS if key not in VERIFIED_SECTIONS):
        raise ValueError("Candidate-provided sections require explicit mixed mode")
    if permissions.show_photo and not permissions.include_profile:
        raise ValueError("Photo requires profile sharing")
    if permissions.include_user_documents and not permissions.show_documents:
        raise ValueError("Documents require explicit document disclosure")


class PassportShareCapabilities(BaseModel):
    policy_version: Literal[2] = 2
    default_mode: Literal["verified_only"] = "verified_only"
    modes: list[SharingMode] = ["verified_only", "verified_and_candidate_provided"]
    verified_only_sections: list[str] = list(VERIFIED_SECTIONS)
    mixed_sections: list[str] = list(MIXED_SECTIONS)
    derived_trust_score: bool = True
    narrow_only_updates: bool = True


class PassportShareCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    label: str = Field(min_length=1, max_length=120)
    sharing_mode: SharingMode = "verified_only"
    expires_at: datetime | None = None
    track_views: bool = True
    permissions: PassportShareV2Permissions = Field(default_factory=PassportShareV2Permissions)

    @model_validator(mode="after")
    def validate_policy(self):
        if self.sharing_mode == "verified_and_candidate_provided":
            # Mixed mode has no implicitly enabled record categories.
            for key in VERIFIED_SECTIONS:
                if key not in self.permissions.model_fields_set:
                    setattr(self.permissions, key, False)
        validate_v2_permissions(self.sharing_mode, self.permissions)
        return self

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
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=120)
    sharing_mode: SharingMode | None = None
    expires_at: datetime | None = None
    track_views: bool | None = None
    permissions: PassportSharePermissionPatch | None = None

    @model_validator(mode="after")
    def no_null_policy(self):
        for key in ("permissions", "sharing_mode", "track_views"):
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError(f"{key} cannot be null")
        return self

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
    policy_version: Literal[1, 2] = 1
    sharing_mode: ResolvedSharingMode = "legacy_mixed"
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
