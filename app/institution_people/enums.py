"""Institution People domain enumerations."""

from __future__ import annotations

from enum import StrEnum


class InstitutionPersonLifecycleStatus(StrEnum):
    CURRENT_STUDENT = "current_student"
    ALUMNI = "alumni"
    WITHDRAWN = "withdrawn"
    INACTIVE = "inactive"


class InstitutionVerificationStatus(StrEnum):
    NOT_STARTED = "not_started"
    PENDING = "pending"
    VERIFIED = "verified"
    DISCREPANCY = "discrepancy"
    CLARIFICATION_REQUIRED = "clarification_required"
    REJECTED = "rejected"
    EXPIRED = "expired"


class InstitutionCredentialStatus(StrEnum):
    ISSUED = "issued"
    REVOKED = "revoked"
    SUPERSEDED = "superseded"


class InstitutionProfessionalField(StrEnum):
    CURRENT_TITLE = "current_title"
    CURRENT_EMPLOYER = "current_employer"
