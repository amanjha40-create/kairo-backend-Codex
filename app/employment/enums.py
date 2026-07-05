"""Employment verification domain enumerations — persisted as VARCHAR for Alembic portability."""

from __future__ import annotations

from enum import StrEnum


class VerificationStatus(StrEnum):
    """Lifecycle for an employment verification case."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    ADDITIONAL_INFO_REQUESTED = "additional_info_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class VerificationMethod(StrEnum):
    """How the applicant proves employment for this case."""

    DOCUMENT = "document"
    EMPLOYER_CONFIRMATION = "employer_confirmation"


class EmployerVerificationDecision(StrEnum):
    """Verifier response captured via magic link."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    DECLINED = "declined"
    ON_HOLD = "on_hold"


class CredentialSubjectType(StrEnum):
    """Verifiable credential kinds handled by the generic magic-link flow."""

    INTERNSHIP = "internship"
    FREELANCE_CONTRACT = "freelance_contract"


class EmploymentType(StrEnum):
    """High-level classification for audit reporting."""

    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    INTERN = "intern"
    GIG = "gig"           # Platform/delivery work (Swiggy, Uber, etc.)
    FREELANCE = "freelance"  # Client/project-based freelance work
    OTHER = "other"


class EmploymentDocumentType(StrEnum):
    """Expected evidence categories — drives reviewer UX and extraction pipelines."""

    PAY_STUB = "pay_stub"
    OFFER_LETTER = "offer_letter"
    FORM_W2 = "form_w2"
    FORM_1099 = "form_1099"
    EMPLOYMENT_CONTRACT = "employment_contract"
    HR_LETTER = "hr_letter"
    RELIEVING_LETTER = "relieving_letter"
    GOVERNMENT_ID = "government_id"
    OTHER = "other"


class DocumentVerificationStatus(StrEnum):
    """Admin review state for each employment evidence file."""

    PENDING_UPLOAD = "pending_upload"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class DocumentExtractionStatus(StrEnum):
    """AI / OCR pipeline coordination — tracks asynchronous worker progress."""

    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class VerificationAuditAction(StrEnum):
    """Append-only audit vocabulary — stable codes for SIEM and compliance exports."""

    EMPLOYMENT_CREATED = "employment_created"
    EMPLOYMENT_UPDATED = "employment_updated"
    EMPLOYMENT_SUBMITTED = "employment_submitted"
    EMPLOYMENT_CANCELLED = "employment_cancelled"
    DOCUMENT_REGISTERED = "document_registered"
    DOCUMENT_UPLOAD_COMPLETED = "document_upload_completed"
    DOCUMENT_VERIFICATION_APPROVED = "document_verification_approved"
    DOCUMENT_VERIFICATION_REJECTED = "document_verification_rejected"
    EXTRACTION_QUEUED = "extraction_queued"
    EXTRACTION_STARTED = "extraction_started"
    EXTRACTION_COMPLETED = "extraction_completed"
    EXTRACTION_FAILED = "extraction_failed"
    VERIFICATION_STATUS_CHANGED = "verification_status_changed"
    REVIEWER_NOTE_RECORDED = "reviewer_note_recorded"
    REVIEW_ASSIGNED = "review_assigned"
    REVIEWER_REMARK_ADDED = "reviewer_remark_added"
    EMPLOYER_VERIFICATION_REQUESTED = "employer_verification_requested"
    EMPLOYER_VERIFICATION_CONFIRMED = "employer_verification_confirmed"
    EMPLOYER_VERIFICATION_DECLINED = "employer_verification_declined"
    EMPLOYER_VERIFICATION_HELD = "employer_verification_held"
