"""Request bodies for employment verification APIs."""

from __future__ import annotations

import re
from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.employment.enums import EmploymentDocumentType, EmploymentType, VerificationMethod, VerificationStatus

_ISO3166_ALPHA2 = re.compile(r"^[A-Z]{2}$")


class CreateEmploymentRequest(BaseModel):
    """Create a draft employment verification case."""

    model_config = ConfigDict(str_strip_whitespace=True)

    subject_full_name: str = Field(..., min_length=1, max_length=255)
    subject_email: EmailStr | None = None
    employer_legal_name: str = Field(..., min_length=2, max_length=512)
    employer_trade_name: str | None = Field(None, max_length=512)
    job_title: str = Field(..., min_length=1, max_length=255)
    employment_type: EmploymentType = EmploymentType.FULL_TIME
    verification_method: VerificationMethod = VerificationMethod.DOCUMENT
    start_date: date
    end_date: date | None = None
    work_location_country: str = Field(..., min_length=2, max_length=2)
    work_location_region: str | None = Field(None, max_length=128)

    @field_validator("work_location_country")
    @classmethod
    def uppercase_country(cls, v: str) -> str:
        u = v.upper()
        if not _ISO3166_ALPHA2.match(u):
            msg = "work_location_country must be ISO 3166-1 alpha-2"
            raise ValueError(msg)
        return u

    @model_validator(mode="after")
    def validate_dates(self) -> CreateEmploymentRequest:
        if self.end_date is not None and self.end_date < self.start_date:
            msg = "end_date cannot be before start_date"
            raise ValueError(msg)
        return self


class UpdateEmploymentRequest(BaseModel):
    """Patch a draft or `additional_info_requested` case (service enforces state)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    subject_full_name: str | None = Field(None, min_length=1, max_length=255)
    subject_email: EmailStr | None = None
    employer_legal_name: str | None = Field(None, min_length=2, max_length=512)
    employer_trade_name: str | None = Field(None, max_length=512)
    job_title: str | None = Field(None, min_length=1, max_length=255)
    employment_type: EmploymentType | None = None
    start_date: date | None = None
    end_date: date | None = None
    work_location_country: str | None = Field(None, min_length=2, max_length=2)
    work_location_region: str | None = Field(None, max_length=128)

    @field_validator("work_location_country")
    @classmethod
    def uppercase_country(cls, v: str | None) -> str | None:
        if v is None:
            return None
        u = v.upper()
        if not _ISO3166_ALPHA2.match(u):
            msg = "work_location_country must be ISO 3166-1 alpha-2"
            raise ValueError(msg)
        return u

    @model_validator(mode="after")
    def validate_dates(self) -> UpdateEmploymentRequest:
        if self.start_date is not None and self.end_date is not None and self.end_date < self.start_date:
            msg = "end_date cannot be before start_date"
            raise ValueError(msg)
        return self


class UploadDocumentRequest(BaseModel):
    """Declared object shape for presigned upload — must match the subsequent S3 PUT and completion digest."""

    model_config = ConfigDict(str_strip_whitespace=True)

    document_type: EmploymentDocumentType
    original_filename: str = Field(..., min_length=1, max_length=512)
    content_type: str = Field(..., min_length=3, max_length=255)
    byte_size: int = Field(..., ge=1, le=500_000_000)


class CompleteUploadRequest(BaseModel):
    """Finalize row after successful PUT — SHA-256 over raw object bytes."""

    model_config = ConfigDict(str_strip_whitespace=True)

    checksum_sha256: str = Field(..., min_length=64, max_length=64)

    @field_validator("checksum_sha256")
    @classmethod
    def lowercase_hex(cls, v: str) -> str:
        import re as _re

        low = v.lower()
        if not _re.fullmatch(r"[a-f0-9]{64}", low):
            msg = "checksum_sha256 must be a 64-character lowercase hex string"
            raise ValueError(msg)
        return low


class DocumentPresignedUrlRequest(UploadDocumentRequest):
    """Flat documents API — scope upload intent to an employment case."""

    employment_id: UUID


class DocumentConfirmUploadRequest(CompleteUploadRequest):
    """Finalize PUT — identifies case + document row."""

    employment_id: UUID
    document_id: UUID


class AdminVerifyRequest(BaseModel):
    """Approve a case — maps to audited transition."""

    model_config = ConfigDict(str_strip_whitespace=True)

    employment_id: UUID
    summary: str = Field(..., min_length=1, max_length=8000)


class AdminRejectRequest(BaseModel):
    """Reject a case — summary required for audit."""

    model_config = ConfigDict(str_strip_whitespace=True)

    employment_id: UUID
    summary: str = Field(..., min_length=1, max_length=8000)


class AdminDocumentDecisionBody(BaseModel):
    """Approve or reject a single employment document."""

    model_config = ConfigDict(str_strip_whitespace=True)

    note: str | None = Field(None, max_length=4000)


class AdminDocumentRejectBody(BaseModel):
    """Reject a document — note required for applicant feedback."""

    model_config = ConfigDict(str_strip_whitespace=True)

    note: str = Field(..., min_length=1, max_length=4000)


class AssignReviewRequest(BaseModel):
    """Assign or reassign the reviewer queue owner — optional automatic triage start."""

    model_config = ConfigDict(str_strip_whitespace=True)

    assignee_user_id: UUID
    start_review: bool = Field(
        True,
        description="When the case is submitted, transition to under_review after assignment.",
    )


class AddRemarkRequest(BaseModel):
    """Internal reviewer note — append-only audit trail."""

    model_config = ConfigDict(str_strip_whitespace=True)

    remark: str = Field(..., min_length=1, max_length=8000)


class AdminDecisionSummaryBody(BaseModel):
    """Approve/reject payload when employment is identified by path parameter."""

    model_config = ConfigDict(str_strip_whitespace=True)

    summary: str = Field(..., min_length=1, max_length=8000)


class AdminVerificationRequest(BaseModel):
    """Admin workflow transition — maps to audited state machine rules in services."""

    model_config = ConfigDict(str_strip_whitespace=True)

    new_status: VerificationStatus
    summary: str | None = Field(None, max_length=8000)
    pending_info_request: str | None = Field(None, max_length=8000)
