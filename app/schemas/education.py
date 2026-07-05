"""DTOs for education records and education documents."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.education.enums import (
    EducationDocumentType,
    EducationLevel,
    EducationVerificationStatus,
)


# --- Education records ---


class EducationCreateRequest(BaseModel):
    institution_name: str = Field(min_length=1, max_length=512)
    degree: str = Field(min_length=1, max_length=255)
    field_of_study: str | None = Field(default=None, max_length=255)
    education_level: EducationLevel
    grade: str | None = Field(default=None, max_length=64)
    start_date: date
    end_date: date | None = None
    is_currently_studying: bool = False

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if self.is_currently_studying and self.end_date is not None:
            raise ValueError("end_date must be null when is_currently_studying is true")
        return self


class EducationUpdateRequest(BaseModel):
    institution_name: str | None = Field(default=None, min_length=1, max_length=512)
    degree: str | None = Field(default=None, min_length=1, max_length=255)
    field_of_study: str | None = Field(default=None, max_length=255)
    education_level: EducationLevel | None = None
    grade: str | None = Field(default=None, max_length=64)
    start_date: date | None = None
    end_date: date | None = None
    is_currently_studying: bool | None = None


class EducationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: uuid.UUID
    user_id: uuid.UUID
    institution_name: str
    degree: str
    field_of_study: str | None = None
    education_level: EducationLevel
    grade: str | None = None
    start_date: date
    end_date: date | None = None
    is_currently_studying: bool
    verification_status: EducationVerificationStatus
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    reviewed_by_user_id: uuid.UUID | None = None
    reviewer_note: str | None = None
    created_at: datetime
    updated_at: datetime


# --- Education documents ---


class EducationDocumentUploadIntentRequest(BaseModel):
    document_type: EducationDocumentType
    original_filename: str = Field(min_length=1, max_length=512)
    content_type: str = Field(min_length=1, max_length=255)
    byte_size: int = Field(gt=0)


class EducationDocumentUploadIntentResponse(BaseModel):
    document_id: uuid.UUID
    object_key: str
    bucket: str
    upload_url: str
    expires_in_seconds: int
    headers_required: dict[str, str]


class EducationDocumentCompleteUploadRequest(BaseModel):
    checksum_sha256: str = Field(min_length=64, max_length=64)


class EducationDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: uuid.UUID
    education_id: uuid.UUID
    document_type: EducationDocumentType
    original_filename: str
    content_type: str
    byte_size: int
    verification_status: str
    verified_at: datetime | None = None
    verified_by_user_id: uuid.UUID | None = None
    reviewer_note: str | None = None
    extracted_payload: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class EducationDocumentDownloadUrlResponse(BaseModel):
    document_id: uuid.UUID
    download_url: str
    expires_in_seconds: int
