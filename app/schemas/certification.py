"""Certification Pydantic schemas."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, Field, model_validator


class CertificationCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    issuing_organization: str = Field(min_length=1, max_length=512)
    issued_date: date
    expiry_date: date | None = None
    does_not_expire: bool = False
    credential_id: str | None = None
    credential_url: AnyHttpUrl | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.does_not_expire and self.expiry_date is not None:
            raise ValueError("expiry_date must be null when does_not_expire is true")
        if self.expiry_date and self.expiry_date < self.issued_date:
            raise ValueError("expiry_date must be on or after issued_date")
        return self


class CertificationUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    issuing_organization: str | None = Field(default=None, min_length=1, max_length=512)
    issued_date: date | None = None
    expiry_date: date | None = None
    does_not_expire: bool | None = None
    credential_id: str | None = None
    credential_url: AnyHttpUrl | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.does_not_expire is True and self.expiry_date is not None:
            raise ValueError("expiry_date must be null when does_not_expire is true")
        if self.expiry_date and self.issued_date and self.expiry_date < self.issued_date:
            raise ValueError("expiry_date must be on or after issued_date")
        return self


class CertificationUploadIntentRequest(BaseModel):
    title: str
    issuing_organization: str
    issued_date: date
    expiry_date: date | None = None
    does_not_expire: bool = False
    credential_id: str | None = None
    credential_url: str | None = None
    # File metadata
    original_filename: str
    content_type: str
    byte_size: int


class CertificationUploadIntentResponse(BaseModel):
    certification_id: UUID
    upload_url: str
    object_key: str


class CertificationCompleteUploadRequest(BaseModel):
    checksum_sha256: str


class CertificationDownloadUrlResponse(BaseModel):
    download_url: str


class CertificationResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    issuing_organization: str
    issued_date: date
    expiry_date: date | None
    does_not_expire: bool
    credential_id: str | None
    credential_url: str | None
    original_filename: str | None
    content_type: str | None
    byte_size: int | None
    verification_status: str
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
