"""Response DTOs for employment verification — typed enums, ORM-friendly."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from app.employment.enums import (
    DocumentExtractionStatus,
    DocumentVerificationStatus,
    EmploymentDocumentType,
    EmploymentType,
    VerificationMethod,
    VerificationStatus,
)
from app.schemas.employer_verification import EmployerVerificationStatusResponse
from app.schemas.pagination import Page

# --- Employment case ---


class EmploymentResponse(BaseModel):
    """Public case projection — list and non-privileged detail."""

    model_config = ConfigDict(
        from_attributes=True,
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    id: uuid.UUID
    subject_full_name: str
    subject_email: str | None
    employer_legal_name: str
    employer_trade_name: str | None
    job_title: str
    employment_type: EmploymentType
    start_date: date
    end_date: date | None
    work_location_country: str | None
    work_location_region: str | None
    verification_method: VerificationMethod = VerificationMethod.DOCUMENT
    verification_status: VerificationStatus
    submitted_at: datetime | None
    reviewed_at: datetime | None
    assigned_reviewer_user_id: uuid.UUID | None = None
    assigned_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class VerificationResponse(EmploymentResponse):
    """Privileged / detail view including reviewer workflow fields."""

    reviewer_summary: str | None
    pending_info_request: str | None
    reviewed_by_user_id: uuid.UUID | None
    employer_verification: EmployerVerificationStatusResponse | None = None
    documents: list[EmploymentDocumentResponse] | None = None


EmploymentListResponse: TypeAlias = Page[EmploymentResponse]


class EmploymentSubmitResponse(BaseModel):
    """Submit acknowledgement wrapping the updated case."""

    employment: EmploymentResponse
    message: str = "Case submitted for verification"


class EmploymentCancelResponse(BaseModel):
    employment: EmploymentResponse
    message: str = "Case cancelled"


# --- Documents ---


class EmploymentDocumentResponse(BaseModel):
    """Stored evidence metadata (no presigned URLs — use upload-intent endpoint)."""

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: uuid.UUID
    employment_id: uuid.UUID
    document_type: EmploymentDocumentType
    original_filename: str
    content_type: str
    byte_size: int
    checksum_sha256: str
    verification_status: DocumentVerificationStatus
    verified_at: datetime | None = None
    verified_by_user_id: uuid.UUID | None = None
    reviewer_note: str | None = None
    extraction_status: DocumentExtractionStatus
    extraction_attempt_count: int
    extraction_started_at: datetime | None
    extraction_completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DocumentUploadIntentResponse(BaseModel):
    """Presigned PUT — clients must not log `upload_url` in analytics or console."""

    document_id: uuid.UUID
    object_key: str
    bucket: str
    upload_url: str
    expires_in_seconds: int
    headers_required: dict[str, str]


class DocumentTypeOption(BaseModel):
    value: str
    label: str
    description: str


class AllowedContentTypeOption(BaseModel):
    mime_type: str
    label: str
    extensions: list[str] = Field(default_factory=list)


class VerificationMethodOption(BaseModel):
    value: str
    label: str
    description: str


class DocumentUploadOptionsResponse(BaseModel):
    """Catalog for clients — document categories, MIME allowlist, and size limits."""

    verification_methods: list[VerificationMethodOption]
    document_types: list[DocumentTypeOption]
    allowed_content_types: list[AllowedContentTypeOption]
    max_upload_bytes: int
    presigned_put_ttl_seconds: int
    extraction_enabled: bool = False
    upload_steps: list[str]


class DocumentUploadCompleteResponse(BaseModel):
    """Upload finalized in S3 — no AI extraction in the current release."""

    document_id: uuid.UUID
    message: str = "Upload complete"


class DocumentDownloadUrlResponse(BaseModel):
    document_id: uuid.UUID
    download_url: str
    expires_in_seconds: int


class ExtractionQueuedAck(DocumentUploadCompleteResponse):
    """Deprecated alias — prefer DocumentUploadCompleteResponse."""

    pass


EmploymentDocumentListResponse: TypeAlias = Page[EmploymentDocumentResponse]


# --- Audit / Timeline ---


class AuditEventResponse(BaseModel):
    """User-facing audit event — shows who did what and when."""

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: uuid.UUID
    employment_id: uuid.UUID
    action: str
    actor_role: str | None = None           # "user" | "hr" | "admin" | "superadmin" | null (system)
    actor_display_name: str | None = None   # Snapshot of full_name or email at time of action
    previous_status: str | None = None
    new_status: str | None = None
    created_at: datetime
    metadata_payload: dict | None = None


AuditEventListResponse: TypeAlias = Page[AuditEventResponse]
