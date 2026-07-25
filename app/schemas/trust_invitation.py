"""Trust invitation DTOs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

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
    requested_verification_types: list[TrustInvitationVerificationType] = Field(default_factory=list)
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


class TrustInvitationTimelineEventResponse(BaseModel):
    id: UUID
    event_type: TrustInvitationEventType
    occurred_at: datetime
    actor_user_id: UUID | None
    actor_email: EmailStr | None
    actor_full_name: str | None
    metadata: dict[str, Any]


class TrustInvitationResponse(BaseModel):
    public_id: UUID
    organization_public_id: UUID
    subject_name: str
    subject_email: EmailStr
    subject_phone: str | None
    purpose: str | None
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
    requested_verification_types: list[TrustInvitationVerificationType]
    expires_at: datetime
    status: TrustInvitationStatus


class TrustInvitationAcceptResponse(BaseModel):
    public_id: UUID
    organization_public_id: UUID
    status: TrustInvitationStatus
    accepted_at: datetime
