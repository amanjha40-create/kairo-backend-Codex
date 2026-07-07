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


class RenderedEmailMessage(BaseModel):
    template_key: str = Field(min_length=1, max_length=100)
    template_version: str = Field(min_length=1, max_length=32)
    to_email: str = Field(min_length=3, max_length=320)
    subject: str = Field(min_length=1, max_length=255)
    text_body: str = Field(min_length=1)
    html_body: str | None = None
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
