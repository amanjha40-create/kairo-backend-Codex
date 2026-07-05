"""Long-polling SQS consumer — separate process from the FastAPI app."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Any

from botocore.exceptions import ClientError
from pydantic import ValidationError

from app.config import get_settings
from app.db.session import async_session_factory, dispose_engine
from app.infrastructure.redis import close_redis_client
from app.infrastructure.redis.client import get_redis_client
from app.infrastructure.sqs.client import get_sqs_client
from app.infrastructure.sqs.envelope import SqsJobEnvelope
from app.logging import setup_logging
from app.workers.registry import get_handler

# SQS message IDs are tracked in Redis for this long to prevent duplicate
# processing when DeleteMessage fails after a successful handler run.
_IDEMPOTENCY_TTL_SECONDS = 86_400  # 24 hours

import app.workers.handlers  # noqa: F401 — register handlers on import

logger = logging.getLogger(__name__)


def _receive_batch(client: Any, queue_url: str, *, wait_seconds: int, max_messages: int) -> list[dict[str, Any]]:
    resp = client.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=max_messages,
        WaitTimeSeconds=wait_seconds,
        AttributeNames=["ApproximateReceiveCount"],
        MessageAttributeNames=["All"],
    )
    return list(resp.get("Messages", []))


def _delete_message(client: Any, queue_url: str, receipt_handle: str) -> None:
    client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)


def _install_shutdown(shutdown: asyncio.Event) -> None:
    def _handler() -> None:
        shutdown.set()

    loop = asyncio.get_running_loop()
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _handler)
    except NotImplementedError:
        # Windows — rely on KeyboardInterrupt for SIGINT
        pass


async def _mark_processed(message_id: str) -> bool:
    """Atomically claim `message_id` in Redis.

    Returns ``True`` if this process is the first to claim it (should run the
    handler), ``False`` if it was already claimed (duplicate — skip).
    The key expires after ``_IDEMPOTENCY_TTL_SECONDS`` so Redis doesn't grow
    without bound.
    """

    redis = await get_redis_client()
    # SET NX returns True on first set, None/False if key already exists.
    result = await redis.set(
        f"sqs:processed:{message_id}",
        "1",
        ex=_IDEMPOTENCY_TTL_SECONDS,
        nx=True,
    )
    return bool(result)


async def _process_message(client: Any, queue_url: str, raw: dict[str, Any]) -> None:
    message_id = raw.get("MessageId", "")
    receipt_handle = raw.get("ReceiptHandle")
    body = raw.get("Body", "")
    if not receipt_handle:
        logger.warning("SQS message missing ReceiptHandle", extra={"message_id": message_id})
        return

    try:
        envelope = SqsJobEnvelope.model_validate_json(body)
    except ValidationError:
        logger.warning(
            "invalid SQS envelope — message will retry until DLQ",
            extra={"message_id": message_id},
        )
        return

    handler = get_handler(envelope.type)
    if handler is None:
        logger.warning(
            "no handler registered — message will retry until DLQ",
            extra={"message_type": envelope.type, "message_id": message_id},
        )
        return

    # Idempotency gate: skip if we already successfully processed this message.
    # This handles the case where the handler succeeded but DeleteMessage failed,
    # causing SQS to re-deliver the message after the visibility timeout.
    is_first = await _mark_processed(message_id)
    if not is_first:
        logger.info(
            "duplicate SQS message — already processed, deleting without re-running handler",
            extra={"message_type": envelope.type, "message_id": message_id},
        )
        try:
            await asyncio.to_thread(_delete_message, client, queue_url, receipt_handle)
        except ClientError:
            pass  # Best-effort; SQS will re-deliver and we'll skip again.
        return

    async with async_session_factory() as session:
        try:
            await handler(envelope.data, session)
            await session.commit()
        except Exception:
            await session.rollback()
            # Release the idempotency key so a retry can re-run the handler.
            redis = await get_redis_client()
            await redis.delete(f"sqs:processed:{message_id}")
            logger.exception(
                "handler failed — message will retry after visibility timeout",
                extra={"message_type": envelope.type, "message_id": message_id},
            )
            return

    try:
        await asyncio.to_thread(_delete_message, client, queue_url, receipt_handle)
    except ClientError as exc:
        logger.warning(
            "DeleteMessage failed after successful handler — idempotency key will prevent re-processing",
            extra={
                "message_id": message_id,
                "error_code": exc.response.get("Error", {}).get("Code", "unknown"),
            },
        )


async def run_worker() -> None:
    """Poll **`SQS_MAIN_QUEUE_URL`** until SIGTERM/SIGINT."""

    setup_logging()
    settings = get_settings()
    queue_url = settings.sqs_main_queue_url
    if not queue_url:
        logger.error("SQS_MAIN_QUEUE_URL is not set — worker exiting")
        sys.exit(1)

    client = get_sqs_client(settings)
    shutdown = asyncio.Event()
    _install_shutdown(shutdown)

    logger.info(
        "SQS worker started",
        extra={
            "queue_configured": True,
            "receive_wait_seconds": settings.sqs_receive_wait_seconds,
            "max_messages": settings.sqs_max_messages_per_poll,
        },
    )

    try:
        while not shutdown.is_set():
            try:
                messages = await asyncio.to_thread(
                    _receive_batch,
                    client,
                    queue_url,
                    wait_seconds=settings.sqs_receive_wait_seconds,
                    max_messages=settings.sqs_max_messages_per_poll,
                )
            except ClientError as exc:
                logger.warning(
                    "ReceiveMessage failed",
                    extra={"error_code": exc.response.get("Error", {}).get("Code", "unknown")},
                )
                await asyncio.sleep(2)
                continue

            if not messages:
                continue

            for msg in messages:
                if shutdown.is_set():
                    break
                await _process_message(client, queue_url, msg)
    finally:
        await dispose_engine()
        await close_redis_client()
        logger.info("SQS worker shutdown complete")
