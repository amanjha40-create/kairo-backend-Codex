"""Certification Pydantic schemas."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class CertificationCreateRequest(BaseModel):
    title: str
    issuing_organization: str
    issued_date: date
    expiry_date: date | None = None
    does_not_expire: bool = False
    credential_id: str | None = None
    credential_url: str | None = None


class CertificationUpdateRequest(BaseModel):
    title: str | None = None
    issuing_organization: str | None = None
    issued_date: date | None = None
    expiry_date: date | None = None
    does_not_expire: bool | None = None
    credential_id: str | None = None
    credential_url: str | None = None


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
