"""Boto3 SQS client factory — shared credentials via standard AWS chain."""

from __future__ import annotations

import boto3
from botocore.client import BaseClient

from app.config import Settings, get_settings


def get_sqs_client(settings: Settings | None = None) -> BaseClient:
    """Return a configured **`sqs`** client (sync API — use **`asyncio.to_thread`** from async code)."""

    s = settings or get_settings()
    session = boto3.session.Session(region_name=s.aws_region)
    kwargs: dict[str, str] = {}
    if s.aws_endpoint_url:
        kwargs["endpoint_url"] = s.aws_endpoint_url
    return session.client("sqs", **kwargs)
