"""Enqueue JSON jobs to SQS without blocking the FastAPI event loop."""

from __future__ import annotations

import asyncio
import logging
from botocore.exceptions import ClientError

from app.config import Settings, get_settings
from app.infrastructure.sqs.client import get_sqs_client
from app.infrastructure.sqs.envelope import SqsJobEnvelope

logger = logging.getLogger(__name__)


def send_json_message_sync(
    envelope: SqsJobEnvelope,
    *,
    queue_url: str | None = None,
    settings: Settings | None = None,
) -> str:
    """Publish one message — synchronous (**boto3**). Returns **MessageId**."""

    s = settings or get_settings()
    url = queue_url or s.sqs_main_queue_url
    if not url:
        msg = "sqs_main_queue_url / SQS_MAIN_QUEUE_URL is required to publish"
        raise ValueError(msg)

    client = get_sqs_client(s)
    try:
        resp = client.send_message(QueueUrl=url, MessageBody=envelope.model_dump_json())
    except ClientError as exc:
        logger.warning(
            "SQS SendMessage failed",
            extra={"error_code": exc.response.get("Error", {}).get("Code", "unknown")},
        )
        raise

    mid = resp.get("MessageId", "")
    return str(mid)


async def send_json_message(
    envelope: SqsJobEnvelope,
    *,
    queue_url: str | None = None,
    settings: Settings | None = None,
) -> str:
    """Async wrapper — runs boto3 in a thread pool."""

    return await asyncio.to_thread(send_json_message_sync, envelope, queue_url=queue_url, settings=settings)


def send_raw_json_sync(
    payload: dict[str, object],
    *,
    queue_url: str | None = None,
    settings: Settings | None = None,
) -> str:
    """Send a dict after validating against **`SqsJobEnvelope`**."""

    envelope = SqsJobEnvelope.model_validate(payload)
    return send_json_message_sync(envelope, queue_url=queue_url, settings=settings)


async def send_raw_json(
    payload: dict[str, object],
    *,
    queue_url: str | None = None,
    settings: Settings | None = None,
) -> str:
    envelope = SqsJobEnvelope.model_validate(payload)
    return await send_json_message(envelope, queue_url=queue_url, settings=settings)
