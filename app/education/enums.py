"""Education enums — levels, document types, verification status."""

from __future__ import annotations

from enum import StrEnum


class EducationLevel(StrEnum):
    """Academic credential level."""

    HIGH_SCHOOL = "high_school"
    DIPLOMA = "diploma"
    BACHELORS = "bachelors"
    MASTERS = "masters"
    DOCTORATE = "doctorate"
    CERTIFICATION = "certification"
    OTHER = "other"


class EducationDocumentType(StrEnum):
    """Supporting evidence for an education record."""

    DEGREE_CERTIFICATE = "degree_certificate"
    TRANSCRIPT = "transcript"
    MARKSHEET = "marksheet"
    ADMISSION_LETTER = "admission_letter"
    ENROLLMENT_PROOF = "enrollment_proof"
    OTHER = "other"


class EducationVerificationStatus(StrEnum):
    """Review state for an education record."""

    DRAFT = "draft"
    PENDING = "pending"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    VERIFIED = "verified"
    REJECTED = "rejected"
