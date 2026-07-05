"""User document type and verification status enums."""

from __future__ import annotations

from enum import StrEnum


class UserDocumentType(StrEnum):
    """Identity / personal documents — tied to a user, not an employment."""

    AADHAAR = "aadhaar"
    PAN = "pan"
    DRIVING_LICENSE = "driving_license"
    PASSPORT = "passport"
    VOTER_ID = "voter_id"
    GOVERNMENT_ID = "government_id"
    OTHER = "other"


class UserDocumentVerificationStatus(StrEnum):
    """Review state for each user identity document."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
