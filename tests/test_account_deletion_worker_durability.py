"""Worker15 queue durability against the integrated ownership-deletion path."""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from app.workers import consumer
from app.workers.defer import DeferMessage
from app.workers.handlers import account_deletion as handler


@asynccontextmanager
async def context(value):
    yield value


@pytest.mark.parametrize("delay", [0, -1, 43201])
def test_deferral_bounds(delay):
    with pytest.raises(ValueError, match="invalid_sqs_deferral"):
        DeferMessage(delay)


@pytest.mark.parametrize("status", ["complete", "operator_review", "unexpected"])
async def test_terminal_or_unknown_state_not_deferred(status):
    session = SimpleNamespace(scalar=AsyncMock(return_value=SimpleNamespace(status=status)))
    assert await handler._defer_seconds(session, uuid4()) is None


async def test_missing_request_not_deferred():
    assert (
        await handler._defer_seconds(SimpleNamespace(scalar=AsyncMock(return_value=None)), uuid4())
        is None
    )


@pytest.mark.parametrize("status", ["purge_pending", "purge_partial"])
@pytest.mark.parametrize("seconds,expected", [(-1, 30), (600, 600), (90000, 43200)])
async def test_retry_timing_bounded(status, seconds, expected):
    request = SimpleNamespace(
        status=status, next_attempt_at=datetime.now(UTC) + timedelta(seconds=seconds)
    )
    session = SimpleNamespace(scalar=AsyncMock(return_value=request))
    assert await handler._defer_seconds(session, uuid4()) == expected


@pytest.mark.parametrize(
    "result,deferred",
    [(None, True), ({"status": "complete"}, False), ({"status": "operator_review"}, False)],
)
async def test_handler_preserves_canonical_result(monkeypatch, result, deferred):
    session = object()
    redis = object()
    monkeypatch.setattr(handler, "async_session_factory", lambda: context(session))
    monkeypatch.setattr(handler, "get_settings", lambda: SimpleNamespace(redis_url="redis://test"))
    monkeypatch.setattr(handler.Redis, "from_url", lambda _: context(redis))
    sweep = AsyncMock(return_value=result)
    timing = AsyncMock(return_value=60)
    monkeypatch.setattr(handler, "sweep_deletions", sweep)
    monkeypatch.setattr(handler, "_defer_seconds", timing)
    did = uuid4()
    if deferred:
        with pytest.raises(DeferMessage) as raised:
            await handler.purge_account({"deletion_id": str(did)}, None)
        assert raised.value.delay_seconds == 60
        timing.assert_awaited_once_with(session, did)
    else:
        await handler.purge_account({"deletion_id": str(did)}, None)
        timing.assert_not_awaited()
    assert sweep.await_args.kwargs == {"deletion_id": did}


@pytest.mark.parametrize("visibility_fails", [False, True])
async def test_deferral_releases_idempotency_without_ack(monkeypatch, visibility_fails):
    events = []
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    redis = SimpleNamespace(delete=AsyncMock(side_effect=lambda _: events.append("release")))
    monkeypatch.setattr(consumer, "async_session_factory", lambda: context(session))
    monkeypatch.setattr(consumer, "get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(consumer, "_mark_processed", AsyncMock(return_value=True))
    job = AsyncMock(side_effect=DeferMessage(60))
    monkeypatch.setattr(consumer, "get_handler", lambda _: job)
    client = Mock()

    def visibility(**kwargs):
        events.append("visibility")
        if visibility_fails:
            raise ClientError({"Error": {"Code": "ServiceUnavailable"}}, "ChangeMessageVisibility")

    client.change_message_visibility.side_effect = visibility
    raw = {
        "MessageId": "synthetic",
        "ReceiptHandle": "receipt",
        "Body": json.dumps({"type": "account.deletion.purge", "data": {}}),
    }
    await consumer._process_message(client, "queue", raw)
    assert events == ["release", "visibility"]
    redis.delete.assert_awaited_once_with("sqs:processed:synthetic")
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
    client.delete_message.assert_not_called()
    client.change_message_visibility.assert_called_once_with(
        QueueUrl="queue", ReceiptHandle="receipt", VisibilityTimeout=60
    )


async def test_redelivery_runs_after_deferral_then_duplicate_is_acknowledged(monkeypatch):
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    redis = SimpleNamespace(delete=AsyncMock())
    monkeypatch.setattr(consumer, "async_session_factory", lambda: context(session))
    monkeypatch.setattr(consumer, "get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(consumer, "_mark_processed", AsyncMock(side_effect=[True, True, False]))
    job = AsyncMock(side_effect=[DeferMessage(30), None])
    monkeypatch.setattr(consumer, "get_handler", lambda _: job)
    client = Mock()
    raw = {
        "MessageId": "synthetic",
        "ReceiptHandle": "receipt",
        "Body": json.dumps({"type": "account.deletion.purge", "data": {}}),
    }
    for _ in range(3):
        await consumer._process_message(client, "queue", raw)
    assert job.await_count == 2
    assert client.delete_message.call_count == 2
    assert client.change_message_visibility.call_count == 1
    redis.delete.assert_awaited_once()
    session.commit.assert_awaited_once()
