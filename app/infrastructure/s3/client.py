"""Async S3 client factory — shared credential chain with SQS."""

from __future__ import annotations

import boto3
from botocore.client import BaseClient

from app.config import Settings, get_settings


def get_s3_client(settings: Settings | None = None) -> BaseClient:
    """Return configured **`s3`** client (sync — wrap with **`asyncio.to_thread`** from routes)."""

    s = settings or get_settings()
    session = boto3.session.Session(region_name=s.aws_region)
    kwargs: dict[str, str] = {}
    if s.aws_endpoint_url:
        kwargs["endpoint_url"] = s.aws_endpoint_url
    return session.client("s3", **kwargs)
