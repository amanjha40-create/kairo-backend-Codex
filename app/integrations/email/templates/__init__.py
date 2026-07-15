"""Transactional email template registry and shared constants."""

from __future__ import annotations

from enum import StrEnum


class EmailTemplateKey(StrEnum):
    TRUST_INVITATION = "trust_invitation"
    VERIFICATION_COMPLETED = "verification_completed"


DEFAULT_TEMPLATE_VERSION = "v1"


__all__ = ["DEFAULT_TEMPLATE_VERSION", "EmailTemplateKey"]
