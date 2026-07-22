"""High-level S3 upload operations — async-safe, configurable TTL, validation helpers."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import Settings
from app.exceptions import ValidationAppError
from app.infrastructure.s3.presign import generate_presigned_put_url, head_object_meta
from app.infrastructure.s3.validation import normalize_primary_mime, validate_upload_declaration

logger = logging.getLogger(__name__)


class S3UploadService:
    """Presigned PUT minting and post-upload HEAD verification for document evidence."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def validate_declaration(self, *, byte_size: int, content_type: str) -> None:
        validate_upload_declaration(byte_size=byte_size, content_type=content_type, settings=self._settings)

    async def presign_put_url(
        self,
        *,
        object_key: str,
        content_type: str,
        ttl_seconds: int | None = None,
    ) -> tuple[str, int]:
        """Return presigned HTTPS PUT URL and effective TTL — never log the URL."""

        bucket = self._settings.s3_documents_bucket
        if not bucket:
            raise ValidationAppError("Document uploads are not configured (missing S3 bucket)")

        ttl = (
            ttl_seconds
            if ttl_seconds is not None
            else self._settings.s3_presigned_put_ttl_seconds
        )

        url = await generate_presigned_put_url(
            bucket=bucket,
            object_key=object_key,
            content_type=content_type,
            ttl_seconds=ttl,
            settings=self._settings,
        )
        return url, ttl

    async def verify_upload_matches_intent(
        self,
        *,
        object_key: str,
        expected_byte_size: int,
        declared_content_type: str,
    ) -> dict[str, Any]:
        """HEAD object — enforce size and Content-Type alignment with the DB intent row."""

        bucket = self._settings.s3_documents_bucket
        if not bucket:
            raise ValidationAppError("Document uploads are not configured")

        meta = await head_object_meta(bucket=bucket, object_key=object_key, settings=self._settings)

        content_length = int(meta.get("ContentLength", 0))
        if content_length != expected_byte_size:
            logger.warning(
                "s3.head.size_mismatch",
                extra={"object_key_prefix": object_key[:48], "expected": expected_byte_size, "actual": content_length},
            )
            raise ValidationAppError("Uploaded object size does not match declared intent")

        head_ct_raw = meta.get("ContentType") or meta.get("content_type")
        if head_ct_raw:
            head_primary = normalize_primary_mime(str(head_ct_raw))
            declared_primary = normalize_primary_mime(declared_content_type)
            if head_primary != declared_primary:
                logger.warning(
                    "s3.head.content_type_mismatch",
                    extra={
                        "object_key_prefix": object_key[:48],
                        "declared": declared_primary,
                        "actual": head_primary,
                    },
                )
                raise ValidationAppError("Uploaded object Content-Type does not match declared intent")
        else:
            logger.warning(
                "s3.head.missing_content_type",
                extra={"object_key_prefix": object_key[:48]},
            )
            raise ValidationAppError("Uploaded object is missing Content-Type metadata")

        return meta

    async def head_object(self, *, object_key: str) -> dict[str, Any]:
        """Read upload metadata without exposing the object or a signed URL."""
        bucket = self._settings.s3_documents_bucket
        if not bucket:
            raise ValidationAppError("Document uploads are not configured")
        return await head_object_meta(bucket=bucket, object_key=object_key, settings=self._settings)

    async def delete_object_best_effort(self, *, object_key: str) -> None:
        """Remove S3 object after DB soft-delete — failures are logged, not raised."""

        bucket = self._settings.s3_documents_bucket
        if not bucket:
            return

        def _delete() -> None:
            from app.infrastructure.s3.client import get_s3_client

            client = get_s3_client(self._settings)
            client.delete_object(Bucket=bucket, Key=object_key)

        try:
            await asyncio.to_thread(_delete)
        except Exception as exc:
            logger.warning(
                "s3.delete_object_failed",
                extra={
                    "object_key_prefix": object_key[:48],
                    "error_type": type(exc).__name__,
                },
            )
