"""Verification request engine enums."""

from __future__ import annotations

from enum import StrEnum


class VerificationRequestType(StrEnum):
    EMPLOYMENT = "employment"
    EDUCATION = "education"
    IDENTITY = "identity"
    DOCUMENT = "document"
    LICENSE = "license"
    MEDICAL = "medical"
    REFERENCE = "reference"
    PLATFORM = "platform"
    CERTIFICATION = "certification"
    CUSTOM = "custom"


class VerificationRequestStatus(StrEnum):
    DRAFT = "draft"
    PENDING_SUBJECT_ACCEPTANCE = "pending_subject_acceptance"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    AWAITING_INFORMATION = "awaiting_information"
    VERIFIED = "verified"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class VerificationRequestEventSource(StrEnum):
    CANDIDATE = "candidate"
    ORGANIZATION = "organization"
    ADMIN = "admin"
    SYSTEM = "system"
    AI = "ai"
