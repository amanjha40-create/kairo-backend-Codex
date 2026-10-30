"""Trust invitation DTOs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.trust_invitations.enums import (
    TrustInvitationDeliveryMethod,
    TrustInvitationDeliveryState,
    TrustInvitationEventType,
    TrustInvitationStatus,
    TrustInvitationVerificationType,
)


class TrustInvitationCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    subject_name: str = Field(min_length=1, max_length=255)
    subject_email: EmailStr
    subject_phone: str | None = Field(default=None, max_length=32)
    purpose: str | None = Field(default=None, max_length=255)
    role_id: UUID | None = None
    requested_verification_types: list[TrustInvitationVerificationType] = Field(
        default_factory=list
    )
    requirements: list["TrustInvitationRequirementRequest"] | None = None
    message: str | None = Field(default=None, max_length=2000)
    delivery_method: TrustInvitationDeliveryMethod = TrustInvitationDeliveryMethod.EMAIL
    mode: Literal["send", "draft"] = "send"
    expires_at: datetime

    @field_validator("subject_phone", "purpose", "message")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("expires_at")
    @classmethod
    def validate_future_expiry(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("expires_at must include timezone information")
        if value <= datetime.now(tz=UTC):
            raise ValueError("expires_at must be in the future")
        return value

    @model_validator(mode="after")
    def unique_requirements(self):
        if self.requirements is not None:
            types = [item.requirement_type for item in self.requirements]
            if len(types) != len(set(types)):
                raise ValueError("Requirement types must be unique")
        return self


class TrustInvitationRequirementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_type: TrustInvitationVerificationType
    mandatory: bool = True
    configuration: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_configuration(self):
        if self.requirement_type == TrustInvitationVerificationType.PROFESSIONAL_REFERENCE:
            raw_count = self.configuration.get(
                "minimum_count", self.configuration.get("reference_count", 1)
            )
            if isinstance(raw_count, bool) or not isinstance(raw_count, int):
                raise ValueError("Professional reference minimum count must be an integer")
            if not 1 <= raw_count <= 10:
                raise ValueError("Professional reference minimum count must be between 1 and 10")
        return self


class TrustInvitationDraftUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    subject_name: str | None = Field(default=None, min_length=1, max_length=255)
    subject_email: EmailStr | None = None
    subject_phone: str | None = Field(default=None, max_length=32)
    purpose: str | None = Field(default=None, max_length=255)
    role_id: UUID | None = None
    requirements: list[TrustInvitationRequirementRequest] | None = None
    message: str | None = Field(default=None, max_length=2000)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("At least one draft field must be supplied")
        return self


class TrustInvitationTimelineEventResponse(BaseModel):
    id: UUID
    event_type: TrustInvitationEventType
    occurred_at: datetime
    actor_user_id: UUID | None
    actor_email: EmailStr | None
    actor_full_name: str | None
    metadata: dict[str, Any]


class TrustInvitationRequirementProgress(BaseModel):
    requirement_type: TrustInvitationVerificationType
    mandatory: bool
    status: Literal["completed", "action_required", "needs_review", "not_started"]
    action: str | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)


class TrustInvitationResponse(BaseModel):
    public_id: UUID
    organization_public_id: UUID
    subject_name: str
    # Retained invitations may belong to a deleted Candidate. Tombstone email
    # addresses are internal identifiers and must not be exposed to clients.
    subject_email: EmailStr | None
    subject_phone: str | None
    purpose: str | None
    role_id: UUID | None = None
    role: str | None = None
    requested_verification_types: list[TrustInvitationVerificationType]
    message: str | None
    status: TrustInvitationStatus
    delivery_method: TrustInvitationDeliveryMethod
    delivery_state: TrustInvitationDeliveryState
    created_by_email: EmailStr
    created_by_full_name: str | None
    expires_at: datetime
    sent_at: datetime | None
    opened_at: datetime | None
    accepted_at: datetime | None
    cancelled_at: datetime | None
    related_verification_request_public_id: UUID | None
    created_at: datetime
    updated_at: datetime
    verification_preferences_snapshot: dict[str, Any] = Field(default_factory=dict)
    requirements_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    requirements_version: int = 1
    lifecycle_state: str = "sent"
    declined_at: datetime | None = None
    completed_at: datetime | None = None
    completed_requirements: int = 0
    required_requirements: int = 0
    requirement_progress: list[TrustInvitationRequirementProgress] = Field(default_factory=list)


class TrustInvitationCreateResponse(TrustInvitationResponse):
    invitation_url: str


class TrustInvitationDetailResponse(TrustInvitationResponse):
    invitation_url: str
    timeline: list[TrustInvitationTimelineEventResponse]


class TrustInvitationSummaryResponse(BaseModel):
    active_count: int
    accepted_count: int
    cancelled_count: int
    expiring_soon_count: int
    draft_count: int


class TrustInvitationPublicLookupResponse(BaseModel):
    public_id: UUID
    organization_name: str
    subject_name: str
    purpose: str | None
    role_id: UUID | None = None
    role: str | None = None
    requested_verification_types: list[TrustInvitationVerificationType]
    expires_at: datetime
    status: TrustInvitationStatus


class TrustInvitationAcceptResponse(BaseModel):
    public_id: UUID
    organization_public_id: UUID
    status: TrustInvitationStatus
    accepted_at: datetime


class CandidateTrustInvitationResponse(BaseModel):
    public_id: UUID
    organization_public_id: UUID
    organization_name: str
    role: str | None = None
    purpose: str | None
    message: str | None
    lifecycle_state: str
    requirements_version: int
    requirements: list[TrustInvitationRequirementProgress]
    completed_requirements: int
    required_requirements: int
    accepted_at: datetime | None
    declined_at: datetime | None
    completed_at: datetime | None
    expires_at: datetime
    share_action: dict[str, Any] | None = None


class TrustInvitationFinalizeRequest(BaseModel):
    passport_share_id: UUID
    consent_version: int


class CandidateInvitationHomeSummary(BaseModel):
    pending_invitation_count: int
    action_required_invitation_count: int
    latest_actionable_invitation: CandidateTrustInvitationResponse | None
