"""Trust invitation domain enums."""

from __future__ import annotations

from enum import StrEnum


class TrustInvitationStatus(StrEnum):
    DRAFT = "draft"
    PENDING = "pending"
    ACCEPTED = "accepted"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class TrustInvitationDeliveryMethod(StrEnum):
    EMAIL = "email"


class TrustInvitationDeliveryState(StrEnum):
    QUEUED = "queued"
    DELIVERED = "delivered"
    OPENED = "opened"
    FAILED = "failed"


class TrustInvitationVerificationType(StrEnum):
    IDENTITY = "identity"
    EMPLOYMENT = "employment"
    EDUCATION = "education"
    CERTIFICATION = "certification"
    PROFESSIONAL_REFERENCE = "professional_reference"


class TrustInvitationEventType(StrEnum):
    CREATED = "created"
    SENT = "sent"
    RESENT = "resent"
    OPENED = "opened"
    ACCEPTED = "accepted"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    DELIVERY_FAILED = "delivery_failed"
    DELETED = "deleted"
