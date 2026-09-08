"""Private source-file storage for organization roster imports.

Source objects are retained under the private documents bucket for 30 days. The
bucket lifecycle policy is expected to enforce deletion; no public URL is ever
created or returned by this adapter.
"""

from __future__ import annotations

import asyncio
from typing import Protocol
from uuid import UUID

from app.config import Settings
from app.exceptions import ValidationAppError
from app.infrastructure.s3.client import get_s3_client
from app.infrastructure.s3.paths import sanitize_filename_for_storage
from app.organization_roster_import.constants import SOURCE_RETENTION_DAYS


class RosterSourceStorage(Protocol):
    async def put_private(self, *, object_key: str, content: bytes, content_type: str) -> None: ...

    async def delete_best_effort(self, *, object_key: str) -> None: ...


class S3RosterSourceStorage:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def put_private(self, *, object_key: str, content: bytes, content_type: str) -> None:
        bucket = self._settings.s3_documents_bucket
        if not bucket:
            raise ValidationAppError(
                "Roster uploads are not configured", code="storage_unavailable"
            )

        def _put() -> None:
            client = get_s3_client(self._settings)
            client.put_object(
                Bucket=bucket,
                Key=object_key,
                Body=content,
                ContentType=content_type,
                ContentDisposition="attachment",
                ServerSideEncryption="AES256",
                Metadata={"retention-days": str(SOURCE_RETENTION_DAYS)},
                Tagging=f"data-class=organization-roster&retention-days={SOURCE_RETENTION_DAYS}",
            )

        await asyncio.to_thread(_put)

    async def delete_best_effort(self, *, object_key: str) -> None:
        bucket = self._settings.s3_documents_bucket
        if not bucket:
            return

        def _delete() -> None:
            get_s3_client(self._settings).delete_object(Bucket=bucket, Key=object_key)

        try:
            await asyncio.to_thread(_delete)
        except Exception:
            # Cleanup must not mask the original database/storage failure.
            return


def build_roster_source_key(
    *,
    settings: Settings,
    organization_id: UUID,
    import_public_id: UUID,
    filename: str,
) -> str:
    root = settings.s3_document_key_prefix.strip("/") or "employment-verification"
    safe_name = sanitize_filename_for_storage(filename, max_length=255)
    return (
        f"{root}/organization-rosters/organizations/{organization_id}"
        f"/imports/{import_public_id}/{safe_name}"
    )
