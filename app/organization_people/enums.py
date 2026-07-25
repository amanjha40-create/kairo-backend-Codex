"""Organization People Registry domain enumerations."""

from __future__ import annotations

from enum import StrEnum


class OrganizationPersonRelationship(StrEnum):
    CANDIDATE = "candidate"
    EMPLOYEE = "employee"
    FORMER_EMPLOYEE = "former_employee"
    CONTRACTOR = "contractor"
    FUTURE_EMPLOYEE = "future_employee"


class OrganizationPersonLifecycleStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    MERGED = "merged"


class OrganizationPersonTrustState(StrEnum):
    UNKNOWN = "unknown"
    PENDING = "pending"
    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    REVOKED = "revoked"


class OrganizationPersonInvitationStatusSummary(StrEnum):
    NOT_INVITED = "not_invited"
    DRAFT = "draft"
    SENT = "sent"
    OPENED = "opened"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class OrganizationPersonVerificationStatusSummary(StrEnum):
    NOT_STARTED = "not_started"
    WAITING_FOR_CANDIDATE = "waiting_for_candidate"
    IN_VERIFICATION = "in_verification"
    CLARIFICATION_REQUIRED = "clarification_required"
    COMPLETED = "completed"
    UNABLE_TO_VERIFY = "unable_to_verify"
    CANCELLED = "cancelled"


class OrganizationPersonPassportStatusSummary(StrEnum):
    NOT_SHARED = "not_shared"
    ACTIVE = "active"
    EXPIRING_SOON = "expiring_soon"
    EXPIRED = "expired"
    ACCESS_REVOKED = "access_revoked"


class OrganizationPersonPassportAccessState(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class OrganizationPersonIdentifierType(StrEnum):
    EMAIL = "email"
    PHONE = "phone"
