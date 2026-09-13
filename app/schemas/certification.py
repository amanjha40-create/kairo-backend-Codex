"""Certification Pydantic schemas."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator, model_validator

from app.validation.urls import normalize_http_url


def _credential_url(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = normalize_http_url(value)
    if normalized is None:
        raise ValueError("Enter a valid credential URL")
    return normalized


class CertificationCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    issuing_organization: str = Field(min_length=1, max_length=512)
    issued_date: date
    expiry_date: date | None = None
    does_not_expire: bool = False
    credential_id: str | None = None
    credential_url: AnyHttpUrl | None = None

    _normalize_credential_url = field_validator("credential_url", mode="before")(_credential_url)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.does_not_expire and self.expiry_date is not None:
            raise ValueError("expiry_date must be null when does_not_expire is true")
        if self.expiry_date and self.issued_date and self.expiry_date < self.issued_date:
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

    _normalize_credential_url = field_validator("credential_url", mode="before")(_credential_url)

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
    issued_date: date | None
    expiry_date: date | None = None
    does_not_expire: bool = False
    credential_id: str | None = None
    credential_url: str | None = None

    _normalize_credential_url = field_validator("credential_url", mode="before")(_credential_url)
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


class CertificationDocumentUploadIntentRequest(BaseModel):
    original_filename: str = Field(min_length=1, max_length=512)
    content_type: str = Field(min_length=1, max_length=255)
    byte_size: int = Field(gt=0)
    checksum_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")

    @field_validator("original_filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        cleaned = value.strip()
        unsafe = "/" in cleaned or "\\" in cleaned or any(ord(char) < 32 for char in cleaned)
        if not cleaned or unsafe:
            raise ValueError("filename must be a plain file name")
        return cleaned

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"application/pdf", "image/jpeg", "image/png"}:
            raise ValueError("unsupported certificate document type")
        return normalized

    @field_validator("byte_size")
    @classmethod
    def validate_byte_size(cls, value: int) -> int:
        if value > 50 * 1024 * 1024:
            raise ValueError("document exceeds the 50 MB limit")
        return value

    @field_validator("checksum_sha256")
    @classmethod
    def normalize_checksum(cls, value: str) -> str:
        return value.lower()


class CertificationDocumentUploadIntentResponse(BaseModel):
    upload_url: str
    upload_token: str
    expires_in_seconds: int
    headers_required: dict[str, str]


class CertificationDocumentCompleteUploadRequest(BaseModel):
    upload_token: str = Field(min_length=32)
    checksum_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")

    @field_validator("checksum_sha256")
    @classmethod
    def normalize_checksum(cls, value: str) -> str:
        return value.lower()


class CertificationDownloadUrlResponse(BaseModel):
    download_url: str


class CertificationResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    issuing_organization: str | None
    issued_date: date | None
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
