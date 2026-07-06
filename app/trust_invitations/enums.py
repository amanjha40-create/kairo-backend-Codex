"""Trust invitation domain enums."""

from __future__ import annotations

from enum import StrEnum


class TrustInvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    CANCELLED = "cancelled"
