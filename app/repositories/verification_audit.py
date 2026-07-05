"""Append-only verification audit stream — compatibility alias for `VerificationRepository`."""

from __future__ import annotations

from app.repositories.verification import VerificationRepository


class VerificationAuditRepository(VerificationRepository):
    """Historical name — delegates to `VerificationRepository` (audit append + listing)."""
