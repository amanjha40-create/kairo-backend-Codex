"""Email template keys and versions."""

from __future__ import annotations

from enum import StrEnum


class EmailTemplateKey(StrEnum):
    TRUST_INVITATION = "trust_invitation"


DEFAULT_TEMPLATE_VERSION = "v1"
