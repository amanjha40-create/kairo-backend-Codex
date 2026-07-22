"""DTOs for user identity documents."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

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

    @field_validator("original_filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or "/" in cleaned or "\\" in cleaned or any(ord(char) < 32 for char in cleaned):
            raise ValueError("filename must be a plain file name")
        return cleaned

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"application/pdf", "image/jpeg", "image/png", "image/webp"}:
            raise ValueError("unsupported document type")
        return normalized

    @field_validator("byte_size")
    @classmethod
    def validate_byte_size(cls, value: int) -> int:
        if value > 50 * 1024 * 1024:
            raise ValueError("document exceeds the 50 MB limit")
        return value


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
