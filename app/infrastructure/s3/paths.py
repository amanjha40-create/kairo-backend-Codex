"""Secure S3 object keys — user + employment isolation with UUID-scoped document folders."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from uuid import UUID

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")


def sanitize_filename_for_storage(name: str, *, max_length: int = 512) -> str:
    """Prevent path traversal and collapse unsafe characters — basename only."""

    base = PurePosixPath(name.replace("\\", "/")).name
    if not base or base in {".", ".."}:
        return "upload.bin"
    cleaned = _SAFE_NAME.sub("_", base).strip("._") or "upload.bin"
    return cleaned[:max_length]


def build_user_avatar_key(*, owner_user_id: UUID, extension: str, prefix: str) -> str:
    """Layout: `{prefix}/users/{uid}/avatar.{ext}`."""
    root = prefix.strip("/").strip() or "employment-verification"
    ext = extension.lstrip(".").lower() or "jpg"
    return f"{root}/users/{owner_user_id}/avatar.{ext}"


def build_user_internship_document_key(
    *, owner_user_id: UUID, internship_id: UUID, document_id: UUID, safe_filename: str, prefix: str,
) -> str:
    root = prefix.strip("/").strip() or "employment-verification"
    fn = safe_filename.strip() or "upload.bin"
    return f"{root}/users/{owner_user_id}/internships/{internship_id}/documents/{document_id}/{fn}"


def build_user_freelance_document_key(
    *, owner_user_id: UUID, freelance_contract_id: UUID, document_id: UUID, safe_filename: str, prefix: str,
) -> str:
    root = prefix.strip("/").strip() or "employment-verification"
    fn = safe_filename.strip() or "upload.bin"
    return f"{root}/users/{owner_user_id}/freelance/{freelance_contract_id}/documents/{document_id}/{fn}"


def build_user_employment_document_key(
    *,
    owner_user_id: UUID,
    employment_id: UUID,
    document_id: UUID,
    safe_filename: str,
    prefix: str,
) -> str:
    """Layout: `{prefix}/users/{uid}/employments/{eid}/documents/{doc_id}/{file}`.

    Isolates tenants by creator user id and ties evidence to a single employment case.
    """

    root = prefix.strip("/").strip() or "employment-verification"
    fn = safe_filename.strip() or "upload.bin"
    return (
        f"{root}/users/{owner_user_id}/employments/{employment_id}"
        f"/documents/{document_id}/{fn}"
    )
