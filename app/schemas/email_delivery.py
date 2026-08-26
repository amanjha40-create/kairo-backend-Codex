"""Internal email delivery schemas."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TrustInvitationEmailTemplateData(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    organization_name: str = Field(min_length=1, max_length=255)
    subject_name: str = Field(min_length=1, max_length=255)
    invitation_url: str = Field(min_length=1, max_length=4096)
    expires_at_iso: str = Field(min_length=1, max_length=64)


class SignupOtpEmailTemplateData(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(min_length=6, max_length=12)
    ttl_minutes: int = Field(ge=1, le=1440)


class PasswordResetEmailTemplateData(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    reset_token: str = Field(min_length=1, max_length=2048)
    ttl_minutes: int = Field(ge=1, le=1440)
    reset_url: str | None = Field(default=None, min_length=1, max_length=4096)


class AdminInvitationEmailTemplateData(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    invited_role_label: str = Field(min_length=1, max_length=255)
    invitation_url: str = Field(min_length=1, max_length=4096)
    expires_at_iso: str = Field(min_length=1, max_length=64)


class EmployerVerificationEmailTemplateData(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    contact_name: str = Field(min_length=1, max_length=255)
    subject_full_name: str = Field(min_length=1, max_length=255)
    employer_name: str = Field(min_length=1, max_length=255)
    job_title: str = Field(min_length=1, max_length=255)
    relationship: str = Field(min_length=1, max_length=255)
    review_url: str = Field(min_length=1, max_length=4096)
    ttl_hours: int = Field(ge=1, le=720)


class InstitutionVerificationEmailTemplateData(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    contact_name: str = Field(min_length=1, max_length=255)
    subject_name: str = Field(min_length=1, max_length=255)
    institution_name: str = Field(min_length=1, max_length=255)
    degree: str = Field(min_length=1, max_length=255)
    programme: str = Field(min_length=1, max_length=255)
    review_url: str = Field(min_length=1, max_length=4096)
    ttl_hours: int = Field(ge=1, le=720)


class VerificationCompletedEmailTemplateData(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    subject_name: str = Field(min_length=1, max_length=255)
    organization_name: str = Field(min_length=1, max_length=255)
    request_type: str = Field(min_length=1, max_length=64)
    completed_at_iso: str = Field(min_length=1, max_length=64)


class RenderedEmailMessage(BaseModel):
    template_key: str = Field(min_length=1, max_length=100)
    template_version: str = Field(min_length=1, max_length=32)
    to_email: str = Field(min_length=3, max_length=320)
    subject: str = Field(min_length=1, max_length=255)
    text_body: str = Field(min_length=1)
    html_body: str | None = None
    from_email: str | None = Field(default=None, min_length=3, max_length=320)
    reply_to: str | None = Field(default=None, min_length=3, max_length=320)
    tags: list[str] = Field(default_factory=list)
    correlation_id: str | None = Field(default=None, max_length=255)
    audit_payload: dict[str, Any] = Field(default_factory=dict)


class EmailSendResult(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    status: str = Field(min_length=1, max_length=32)
    provider_message_id: str | None = Field(default=None, max_length=255)
    error_code: str | None = Field(default=None, max_length=100)
    error_message: str | None = None


class EmailSendJobPayload(BaseModel):
    email_delivery_log_public_id: UUID
    message: RenderedEmailMessage
