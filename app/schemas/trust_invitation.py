"""Trust invitation DTOs."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.trust_invitations.enums import TrustInvitationStatus


class TrustInvitationCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    subject_name: str = Field(min_length=1, max_length=255)
    subject_email: EmailStr
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def validate_future_expiry(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("expires_at must include timezone information")
        if value <= datetime.now(tz=UTC):
            raise ValueError("expires_at must be in the future")
        return value


class TrustInvitationResponse(BaseModel):
    public_id: UUID
    organization_public_id: UUID
    subject_name: str
    subject_email: EmailStr
    status: TrustInvitationStatus
    expires_at: datetime
    accepted_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TrustInvitationCreateResponse(TrustInvitationResponse):
    invitation_url: str


class TrustInvitationPublicLookupResponse(BaseModel):
    public_id: UUID
    organization_name: str
    subject_name: str
    expires_at: datetime
    status: TrustInvitationStatus


class TrustInvitationAcceptResponse(BaseModel):
    public_id: UUID
    organization_public_id: UUID
    status: TrustInvitationStatus
    accepted_at: datetime
