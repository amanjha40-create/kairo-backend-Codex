"""Presigned PUT URLs for direct browser → S3 uploads (TLS in transit; SSE-KMS optional at bucket policy)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from botocore.exceptions import ClientError

from app.config import Settings, get_settings
from app.infrastructure.s3.client import get_s3_client

logger = logging.getLogger(__name__)


async def generate_presigned_put_url(
    *,
    bucket: str,
    object_key: str,
    content_type: str,
    ttl_seconds: int,
    settings: Settings | None = None,
) -> str:
    """Return a time-limited HTTPS PUT URL — never log full URL (contains sig)."""

    s = settings or get_settings()
    client = get_s3_client(s)

    def _sync() -> str:
        try:
            return client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": bucket,
                    "Key": object_key,
                    "ContentType": content_type,
                },
                ExpiresIn=ttl_seconds,
            )
        except ClientError as exc:
            logger.warning(
                "presigned PUT generation failed",
                extra={"error_code": exc.response.get("Error", {}).get("Code", "unknown")},
            )
            raise

    return await asyncio.to_thread(_sync)


async def generate_presigned_get_url(
    *,
    bucket: str,
    object_key: str,
    ttl_seconds: int = 300,
    settings: Settings | None = None,
) -> str:
    """Return a time-limited HTTPS GET URL for viewing/downloading a private S3 object."""

    s = settings or get_settings()
    client = get_s3_client(s)

    def _sync() -> str:
        try:
            return client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": object_key},
                ExpiresIn=ttl_seconds,
            )
        except ClientError as exc:
            logger.warning(
                "presigned GET generation failed",
                extra={"error_code": exc.response.get("Error", {}).get("Code", "unknown")},
            )
            raise

    return await asyncio.to_thread(_sync)


async def head_object_meta(
    *,
    bucket: str,
    object_key: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Fetch object metadata after upload — validates existence and ContentType."""

    s = settings or get_settings()
    client = get_s3_client(s)

    def _sync() -> dict[str, Any]:
        return client.head_object(Bucket=bucket, Key=object_key)

    return await asyncio.to_thread(_sync)
