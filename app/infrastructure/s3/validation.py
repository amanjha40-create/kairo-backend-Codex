"""MIME and declared-size validation for presigned upload intents."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.exceptions import ValidationAppError

if TYPE_CHECKING:
    from app.config import Settings


def normalize_primary_mime(value: str) -> str:
    """Strip parameters (e.g. charset) for stable allowlist comparison."""

    return value.split(";")[0].strip().lower()


def validate_upload_declaration(*, byte_size: int, content_type: str, settings: "Settings") -> None:
    """Enforce platform limits and MIME allowlist before minting a presigned URL."""

    if byte_size < 1:
        raise ValidationAppError("Declared file size is invalid")
    if byte_size > settings.employment_max_upload_bytes:
        raise ValidationAppError("Declared file size exceeds platform limits")

    primary = normalize_primary_mime(content_type)
    if not primary:
        raise ValidationAppError("Content type is required")

    allowed = {normalize_primary_mime(x) for x in settings.s3_allowed_upload_content_types}
    if primary not in allowed:
        raise ValidationAppError("Content type is not allowed for uploads")
