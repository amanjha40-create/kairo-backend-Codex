"""Exact invocation counters: disposable local ledger and fake S3 SDK only."""

import asyncio
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from sqlalchemy import delete, select

from app.config import get_settings
from app.db.session import async_session_factory
from app.models.account_deletion import AccountDeletion, AccountDeletionItem
from app.services.account_deletion_inventory import identity
from app.services.account_deletion_purge import PurgeStorage, sweep_deletions
from app.services.account_deletion_telemetry import current_metrics
from app.workers import account_deletion_sweeper as cli

PRIVATE = "private-filename.pdf?token=synthetic-secret"


class S3:
    def __init__(self):
        self.versions = []
        self.markers = []
        self.calls = []
        self.error = None

    def list_object_versions(self, **kwargs):
        return {"Versions": list(self.versions), "DeleteMarkers": list(self.markers)}

    def delete_object(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        match = {"Key": kwargs["Key"], "VersionId": kwargs["VersionId"]}
        self.versions = [row for row in self.versions if row != match]
        self.markers = [row for row in self.markers if row != match]


@pytest.fixture
async def ledger():
    now, uid, rid = datetime.now(UTC), uuid4(), uuid4()
    settings = get_settings().model_copy(update={"s3_documents_bucket": "synthetic-bucket"})
    sdk = S3()
    storage = PurgeStorage.__new__(PurgeStorage)
    storage.client = sdk
    scope = f"test/user-documents/{uid}/"
    async with async_session_factory() as session:
        session.add(
            AccountDeletion(
                id=rid,
                user_id=uid,
                storage_bucket="synthetic-bucket",
                storage_prefix="test",
                requested_at=now,
                db_committed_at=now,
                next_attempt_at=now,
            )
        )
        await session.commit()

    async def add(*, status="pending", due=None, malformed=False, kind="object"):
        key = scope + f"{uuid4()}/synthetic.pdf"
        if malformed:
            key = "https://private.example/" + PRIVATE
        if kind == "namespace":
            key = scope
        async with async_session_factory() as session:
            session.add(
                AccountDeletionItem(
                    deletion_id=rid,
                    identity_hash=identity(kind, key),
                    source_type="vault",
                    kind=kind,
                    object_key=key,
                    scope_prefix=scope,
                    status=status,
                    next_attempt_at=due or now,
                )
            )
            await session.commit()
        if kind == "object":
            sdk.versions.append({"Key": key, "VersionId": "synthetic-version"})
        return key

    async def run(*, target=rid, at=now, session=None):
        if session is not None:
            return await sweep_deletions(
                session, settings, None, storage=storage, deletion_id=target, now=at
            )
        async with async_session_factory() as fresh:
            return await sweep_deletions(
                fresh, settings, None, storage=storage, deletion_id=target, now=at
            )

    yield SimpleNamespace(
        id=rid, uid=uid, now=now, scope=scope, sdk=sdk, add=add, run=run, settings=settings
    )
    async with async_session_factory() as session:
        await session.execute(
            delete(AccountDeletionItem).where(AccountDeletionItem.deletion_id == rid)
        )
        await session.execute(delete(AccountDeletion).where(AccountDeletion.id == rid))
        await session.commit()


def summary(capsys):
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(records) == 1
    record = records[0]
    assert record["event"] == "account_deletion_sweep_completed"
    for name, value in record.items():
        if name not in {"event", "invocation_result", "failure_category"}:
            assert type(value) is int and value >= 0
    assert current_metrics() is None
    return record


def counts(record, scanned, claimed, attempted, succeeded=0, missing=0):
    assert [record[k] for k in ("rows_scanned", "rows_claimed", "objects_attempted")] == [
        scanned,
        claimed,
        attempted,
    ]
    assert record["objects_succeeded"] == succeeded
    assert record["objects_missing"] == missing


async def test_empty_sweep_logs_one_zero_work_summary(ledger, capsys):
    assert await ledger.run(target=uuid4()) is None
    record = summary(capsys)
    counts(record, 0, 0, 0)
    assert record["requests_claimed"] == 0
    assert record["invocation_result"] == "no_work"


async def test_one_claimed_object_success(ledger, capsys):
    await ledger.add()
    assert (await ledger.run())["status"] == "complete"
    record = summary(capsys)
    counts(record, 1, 1, 1, 1)
    assert record["requests_claimed"] == 1
    assert record["objects_already_absent"] == 0
    assert record["invocation_result"] == "success"


async def test_multiple_objects_versions_and_delete_markers(ledger, capsys):
    key = await ledger.add()
    await ledger.add()
    ledger.sdk.versions.append({"Key": key, "VersionId": "second-version"})
    ledger.sdk.markers.append({"Key": key, "VersionId": "delete-marker"})
    await ledger.run()
    counts(summary(capsys), 2, 2, 4, 4)
    assert len(ledger.sdk.calls) == 4


@pytest.mark.parametrize("reason", ["complete", "review", "future"])
async def test_seen_but_not_claimed(ledger, capsys, reason):
    await ledger.add(
        status="pending" if reason == "future" else reason,
        due=ledger.now + timedelta(days=1) if reason == "future" else None,
    )
    await ledger.run()
    counts(summary(capsys), 1, 0, 0)
    assert ledger.sdk.calls == []


async def test_missing_before_delete_is_not_an_attempt(ledger, capsys):
    await ledger.add()
    ledger.sdk.versions.clear()
    await ledger.run()
    record = summary(capsys)
    counts(record, 1, 1, 0)
    assert record["objects_already_absent"] == 1


@pytest.mark.parametrize("code", ["NoSuchKey", "NoSuchVersion"])
async def test_missing_during_delete_is_an_attempt_not_success(ledger, capsys, code, monkeypatch):
    await ledger.add()

    def disappeared(**kwargs):
        ledger.sdk.calls.append(kwargs)
        ledger.sdk.versions.clear()
        raise ClientError({"Error": {"Code": code, "Message": PRIVATE}}, "DeleteObject")

    monkeypatch.setattr(ledger.sdk, "delete_object", disappeared)
    await ledger.run()
    record = summary(capsys)
    counts(record, 1, 1, 1, missing=1)
    assert record["objects_already_absent"] == 0
    assert record["retryable_failures"] == record["permanent_failures"] == 0


@pytest.mark.parametrize("permanent", [False, True])
async def test_storage_failure_counts_are_invocation_local_and_sanitized(ledger, capsys, permanent):
    await ledger.add()
    ledger.sdk.error = (
        ClientError({"Error": {"Code": "AccessDenied", "Message": PRIVATE}}, "DeleteObject")
        if permanent
        else ConnectionError(PRIVATE)
    )
    result = await ledger.run()
    record = summary(capsys)
    counts(record, 1, 1, 1)
    assert record["permanent_failures"] == int(permanent)
    assert record["retryable_failures"] == int(not permanent)
    assert record["invocation_result"] == ("review" if permanent else "partial")
    assert PRIVATE not in json.dumps(record)
    assert result["status"] == ("operator_review" if permanent else "purge_partial")
    if not permanent:
        ledger.sdk.error = None
        await ledger.run(at=ledger.now + timedelta(hours=2))
        record = summary(capsys)
        counts(record, 1, 1, 1, 1)
        assert record["retryable_failures"] == 0


async def test_malformed_reference_claimed_without_storage(ledger, capsys):
    await ledger.add(malformed=True)
    await ledger.run()
    record = summary(capsys)
    counts(record, 1, 1, 0)
    assert record["permanent_failures"] == 1
    assert record["failure_category"] == "ownership_or_configuration_guard"
    assert PRIVATE not in json.dumps(record)


async def test_locked_parent_is_unobserved_and_duplicate_is_not_processed(ledger, capsys):
    await ledger.add()
    async with async_session_factory() as locked:
        await locked.scalar(
            select(AccountDeletion).where(AccountDeletion.id == ledger.id).with_for_update()
        )
        assert await ledger.run() is None
        counts(summary(capsys), 0, 0, 0)
    await ledger.run()
    counts(summary(capsys), 1, 1, 1, 1)
    await ledger.run(at=ledger.now + timedelta(days=2))
    counts(summary(capsys), 1, 0, 0)
    assert len(ledger.sdk.calls) == 1


async def test_commit_failure_keeps_attempts_but_rolls_back_and_raises(ledger, capsys, monkeypatch):
    await ledger.add()
    async with async_session_factory() as session:

        async def fail():
            raise RuntimeError(PRIVATE)

        monkeypatch.setattr(session, "commit", fail)
        with pytest.raises(RuntimeError):
            await ledger.run(session=session)
    record = summary(capsys)
    counts(record, 1, 1, 1, 1)
    assert record["invocation_result"] == "failed" and record["invocation_failures"] == 1
    assert PRIVATE not in json.dumps(record)
    async with async_session_factory() as session:
        item = await session.scalar(
            select(AccountDeletionItem).where(AccountDeletionItem.deletion_id == ledger.id)
        )
        assert item.status == "pending" and item.attempts == 0


async def test_cancellation_emits_partial_counts_and_is_not_swallowed(ledger, capsys):
    await ledger.add()
    ledger.sdk.error = asyncio.CancelledError(PRIVATE)
    with pytest.raises(asyncio.CancelledError):
        await ledger.run()
    record = summary(capsys)
    counts(record, 1, 1, 1)
    assert record["invocation_result"] == "failed"


async def test_discovery_does_not_inflate_delete_attempts(ledger, capsys):
    await ledger.add(kind="namespace")
    ledger.sdk.versions.append({"Key": ledger.scope + "orphan.pdf", "VersionId": "v1"})
    assert (await ledger.run())["status"] == "purge_pending"
    counts(summary(capsys), 1, 1, 0)
    assert ledger.sdk.calls == []
    await ledger.run(at=ledger.now + timedelta(hours=2))
    counts(summary(capsys), 2, 2, 1, 1)


async def test_existing_work_limit_counts_seen_but_unprocessed_row(ledger, capsys):
    async with async_session_factory() as session:
        for index in range(251):
            key = ledger.scope + f"synthetic-{index}.pdf"
            session.add(
                AccountDeletionItem(
                    deletion_id=ledger.id,
                    identity_hash=identity("object", key),
                    source_type="vault",
                    kind="object",
                    object_key=key,
                    scope_prefix=ledger.scope,
                    status="pending",
                    next_attempt_at=ledger.now,
                )
            )
        await session.commit()
    result = await ledger.run()
    record = summary(capsys)
    counts(record, 251, 250, 0)
    assert record["objects_already_absent"] == 250
    assert result["pending"] == 1


async def test_listing_failure_does_not_count_a_delete(ledger, capsys, monkeypatch):
    await ledger.add()

    def fail(**kwargs):
        raise ConnectionError(PRIVATE)

    monkeypatch.setattr(ledger.sdk, "list_object_versions", fail)
    await ledger.run()
    record = summary(capsys)
    counts(record, 1, 1, 0)
    assert record["retryable_failures"] == 1


async def test_overlapping_invocations_keep_separate_counters(ledger, capsys, monkeypatch):
    await ledger.add()
    entered, release = asyncio.Event(), asyncio.Event()
    original = PurgeStorage.purge

    async def wait(self, bucket, key):
        entered.set()
        await release.wait()
        await original(self, bucket, key)

    monkeypatch.setattr(PurgeStorage, "purge", wait)
    first = asyncio.create_task(ledger.run())
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert await ledger.run() is None
        counts(summary(capsys), 0, 0, 0)
    finally:
        release.set()
        await first
    counts(summary(capsys), 1, 1, 1, 1)
    assert len(ledger.sdk.calls) == 1


async def test_cli_and_service_emit_one_summary(ledger, capsys, monkeypatch):
    class RedisContext:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *_):
            return False

    async def run(*_):
        return await ledger.run(target=uuid4())

    monkeypatch.setattr(cli.Redis, "from_url", lambda _: RedisContext())
    monkeypatch.setattr(cli, "sweep_deletions", run)
    await cli.main(execute=True)
    counts(summary(capsys), 0, 0, 0)


async def test_cli_startup_failure_emits_sanitized_summary(ledger, capsys, monkeypatch):
    def fail():
        raise RuntimeError(PRIVATE)

    monkeypatch.setattr(cli, "get_settings", fail)
    with pytest.raises(RuntimeError):
        await cli.main(execute=True)
    record = summary(capsys)
    counts(record, 0, 0, 0)
    assert record["invocation_failures"] == 1
    assert PRIVATE not in json.dumps(record)


def test_cli_nonzero_failure_exit_and_no_exception_leak():
    source = """
import runpy, sys
import app.config
import app.db.session
def fail():
    raise RuntimeError('private-filename.pdf?token=synthetic-secret')
app.config.get_settings = fail
sys.argv = ['sweeper', '--execute']
runpy.run_module('app.workers.account_deletion_sweeper', run_name='__main__')
"""
    result = subprocess.run(
        [sys.executable, "-c", source], capture_output=True, text=True, timeout=15
    )
    assert result.returncode != 0
    record = json.loads(result.stdout)
    assert record["invocation_result"] == "failed"
    assert "account_deletion_sweep_failed" in result.stderr
    assert PRIVATE not in result.stdout + result.stderr


async def test_summary_has_no_private_or_ambient_logging_context(ledger, capsys):
    from app.logging.context import bind_user_context

    key = await ledger.add()
    bind_user_context(str(ledger.uid))
    try:
        ledger.sdk.error = RuntimeError(PRIVATE)
        await ledger.run()
    finally:
        bind_user_context(None)
    record = summary(capsys)
    encoded = json.dumps(record)
    for value in (str(ledger.uid), str(ledger.id), key, PRIVATE, "synthetic-bucket", "https://"):
        assert value not in encoded
    assert set(record) == {
        "event",
        "rows_scanned",
        "rows_claimed",
        "requests_claimed",
        "objects_attempted",
        "objects_succeeded",
        "objects_missing",
        "objects_already_absent",
        "retryable_failures",
        "permanent_failures",
        "invocation_failures",
        "invocation_result",
        "failure_category",
        "duration_ms",
    }
