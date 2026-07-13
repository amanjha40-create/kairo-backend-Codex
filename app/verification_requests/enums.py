"""Verification request engine enums."""

from __future__ import annotations

from enum import StrEnum


class VerificationContactType(StrEnum):
    HR = "hr"
    MANAGER = "manager"
    FOUNDER = "founder"
    AUTHORIZED_REPRESENTATIVE = "authorized_representative"
    OTHER = "other"


class VerificationContactReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"


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


class VerificationRequestOriginType(StrEnum):
    TRUST_INVITATION = "trust_invitation"
    SUBJECT_INITIATED = "subject_initiated"
    ORGANIZATION_CREATED = "organization_created"
    ADMIN_CREATED = "admin_created"
    API = "api"
    SYSTEM = "system"


class VerificationRequestStatus(StrEnum):
    DRAFT = "draft"
    PENDING_SUBJECT_ACCEPTANCE = "pending_subject_acceptance"
    ACCEPTED = "accepted"
    PENDING_SUBJECT_SUBMISSION = "pending_subject_submission"
    PENDING_ADMIN_REVIEW = "pending_admin_review"
    AWAITING_SUBJECT_CORRECTIONS = "awaiting_subject_corrections"
    PENDING_ADMIN_RE_REVIEW = "pending_admin_re_review"
    APPROVED_FOR_ORGANIZATION_VERIFICATION = "approved_for_organization_verification"
    PENDING_ORGANIZATION_RESOLUTION = "pending_organization_resolution"
    PENDING_ORGANIZATION_ACCEPTANCE = "pending_organization_acceptance"
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
