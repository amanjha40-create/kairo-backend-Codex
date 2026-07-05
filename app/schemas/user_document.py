"""DTOs for user identity documents."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.user_documents.enums import UserDocumentType, UserDocumentVerificationStatus


class UserDocumentResponse(BaseModel):
    """Public DTO for a user document."""

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: uuid.UUID
    user_id: uuid.UUID
    document_type: UserDocumentType
    document_number: str | None = None
    original_filename: str
    content_type: str
    byte_size: int
    verification_status: UserDocumentVerificationStatus
    verified_at: datetime | None = None
    verified_by_user_id: uuid.UUID | None = None
    reviewer_note: str | None = None
    expires_at: date | None = None
    extracted_payload: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class UserDocumentUploadIntentRequest(BaseModel):
    document_type: UserDocumentType
    original_filename: str = Field(min_length=1, max_length=512)
    content_type: str = Field(min_length=1, max_length=255)
    byte_size: int = Field(gt=0)
    document_number: str | None = Field(default=None, max_length=128)
    expires_at: date | None = None


class UserDocumentUploadIntentResponse(BaseModel):
    document_id: uuid.UUID
    object_key: str
    bucket: str
    upload_url: str
    expires_in_seconds: int
    headers_required: dict[str, str]


class UserDocumentCompleteUploadRequest(BaseModel):
    checksum_sha256: str = Field(min_length=64, max_length=64)


class UserDocumentUpdateRequest(BaseModel):
    document_number: str | None = Field(default=None, max_length=128)
    expires_at: date | None = None


class UserDocumentDownloadUrlResponse(BaseModel):
    document_id: uuid.UUID
    download_url: str
    expires_in_seconds: int
