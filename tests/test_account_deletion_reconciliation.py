"""Real PostgreSQL locks; synthetic ledger fixtures and no external services."""

import asyncio
import json
import sys
from unittest.mock import AsyncMock

import pytest
import test_account_deletion_workflow as workflow
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError

from app.db.session import async_session_factory, engine
from app.ops import account_deletion_recovery as cli
from app.services.account_deletion_recovery import (
    LOCK_ID,
    RecoveryRefused,
    acquire_reconciliation_lock,
    audit_recovery,
    begin_readonly,
)

case = workflow.case


def events(capsys):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def names(items):
    return [item["event"].removeprefix("account_deletion_reconciliation.") for item in items]


async def can_lock():
    async with engine.connect() as connection:
        await begin_readonly(connection)
        return await connection.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": LOCK_ID}
        )


async def test_two_connections_readonly_lock_rollback_and_no_write():
    async with engine.connect() as first, engine.connect() as second:
        await begin_readonly(first)
        await acquire_reconciliation_lock(first)
        assert await first.scalar(text("SHOW transaction_read_only")) == "on"
        await begin_readonly(second)
        assert not await second.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": LOCK_ID}
        )
        with pytest.raises(DBAPIError):
            await first.execute(text("DELETE FROM account_deletions WHERE false"))
        await first.rollback()
        await second.rollback()
        await begin_readonly(second)
        await acquire_reconciliation_lock(second)
    assert await can_lock()


async def test_transaction_commit_also_releases_lock():
    async with engine.connect() as first:
        await begin_readonly(first)
        await acquire_reconciliation_lock(first)
        assert not await can_lock()
        await first.commit()
        assert await can_lock()


async def test_backend_disconnect_releases_lock():
    async with engine.connect() as first:
        await begin_readonly(first)
        await acquire_reconciliation_lock(first)
        assert not await can_lock()
        await first.invalidate()
    assert await can_lock()


async def test_concurrent_cli_skips_without_scanning_then_reacquires(monkeypatch, capsys):
    entered = asyncio.Event()
    release = asyncio.Event()
    real_lock = acquire_reconciliation_lock

    async def hold_after_real_lock(session):
        await real_lock(session)
        assert await session.scalar(text("SHOW transaction_read_only")) == "on"
        entered.set()
        await release.wait()

    monkeypatch.setattr(
        "app.services.account_deletion_recovery.acquire_reconciliation_lock", hold_after_real_lock
    )
    scanned = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        if "account_deletion" in statement.lower() and "select" in statement.lower():
            scanned.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    first = asyncio.create_task(cli.run(cli.parser().parse_args(["--dry-run"])))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert scanned == []
        assert await cli.run(cli.parser().parse_args(["--dry-run"])) == 0
        assert scanned == []
        second_events = events(capsys)
        assert names(second_events) == ["started", "started", "skipped_overlap"]
        release.set()
        assert await asyncio.wait_for(first, 5) == 0
        assert scanned
        assert names(events(capsys)) == ["account_deletion_recovery_audit", "completed"]
        assert await cli.run(cli.parser().parse_args([])) == 0
        assert names(events(capsys)) == ["started", "account_deletion_recovery_audit", "completed"]
    finally:
        release.set()
        if not first.done():
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
        event.remove(engine.sync_engine, "before_cursor_execute", capture)


@pytest.mark.parametrize("failure", ["exception", "cancel", "timeout"])
async def test_failure_or_cancellation_releases_same_scan_lock(failure, monkeypatch, capsys):
    entered = asyncio.Event()
    real_lock = acquire_reconciliation_lock

    async def fail_while_locked(session):
        await real_lock(session)
        entered.set()
        if failure == "exception":
            raise RuntimeError("sensitive-person@example.invalid/private-key")
        await asyncio.Event().wait()

    monkeypatch.setattr(
        "app.services.account_deletion_recovery.acquire_reconciliation_lock", fail_while_locked
    )
    task = asyncio.create_task(cli.run(cli.parser().parse_args([])))
    await asyncio.wait_for(entered.wait(), 5)
    if failure == "exception":
        with pytest.raises(RuntimeError):
            await task
    elif failure == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(task, 0.01)
    assert await can_lock()
    output = events(capsys)
    assert names(output) == ["started", "failed"]
    assert "sensitive-person" not in json.dumps(output)


async def test_dry_run_excludes_execute_before_execute_scan(monkeypatch, capsys):
    audit = AsyncMock()
    recover = AsyncMock()
    monkeypatch.setattr(cli, "audit_recovery", audit)
    monkeypatch.setattr(cli, "recover_one", recover)
    async with engine.connect() as held:
        await begin_readonly(held)
        await acquire_reconciliation_lock(held)
        with pytest.raises(RecoveryRefused, match="another_recovery_running"):
            await cli.run(cli.parser().parse_args(["--execute"]))
        audit.assert_not_called()
        recover.assert_not_called()
    assert events(capsys) == []


async def test_execute_holds_shared_lock_through_recovery(monkeypatch, capsys):
    from uuid import uuid4

    did = str(uuid4())
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_recover(*_args):
        entered.set()
        await release.wait()
        return {"review": 0, "last_error_category": None}

    # The execute audit/results are synthetic; advisory acquisition is real DB.
    real_audit = cli.audit_recovery

    async def audit(session, **kwargs):
        if kwargs.get("acquire_lock"):
            return await real_audit(session, **kwargs)
        return {"eligible_ids": [did], "review_requests": 0}

    monkeypatch.setattr(cli, "audit_recovery", audit)
    monkeypatch.setattr(cli, "recover_one", blocked_recover)
    task = asyncio.create_task(cli.run(cli.parser().parse_args(["--execute"])))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        events(capsys)
        assert await cli.run(cli.parser().parse_args([])) == 0
        assert names(events(capsys)) == ["started", "skipped_overlap"]
        release.set()
        assert await asyncio.wait_for(task, 5) == 0
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
    assert await can_lock()


async def test_completion_after_dispose_and_zero_records(monkeypatch, capsys):
    from uuid import uuid4

    original_dispose = type(engine).dispose
    disposed = []

    async def dispose(self):
        disposed.append(True)
        await original_dispose(self)

    original_emit = cli.emit

    def emit(value):
        if value["event"].endswith(".completed"):
            assert disposed
        original_emit(value)

    monkeypatch.setattr(type(engine), "dispose", dispose)
    monkeypatch.setattr(cli, "emit", emit)
    assert await cli.run(cli.parser().parse_args(["--deletion-id", str(uuid4())])) == 0
    output = events(capsys)
    assert names(output) == ["started", "account_deletion_recovery_audit", "completed"]
    completed = output[-1]
    assert completed["examined_count"] == 0
    assert completed["stranded_count"] is None
    assert completed["duration_ms"] >= 0
    assert completed["dry_run"] is True
    assert set(completed) == {
        "event",
        "dry_run",
        "timestamp",
        "duration_ms",
        "examined_count",
        "overdue_count",
        "review_required_count",
        "stranded_count",
        "stranded_count_basis",
        "stranded_candidate_count",
    }


async def test_dispose_failure_emits_no_completion(monkeypatch, capsys):
    original = type(engine).dispose

    async def dispose(self):
        await original(self)
        raise RuntimeError("private-connection-string")

    monkeypatch.setattr(type(engine), "dispose", dispose)
    with pytest.raises(RuntimeError):
        await cli.run(cli.parser().parse_args([]))
    monkeypatch.setattr(type(engine), "dispose", original)
    output = events(capsys)
    assert "completed" not in names(output)
    assert names(output)[-1] == "failed"
    assert "private-connection" not in json.dumps(output)


async def test_readonly_audit_integration_no_dml_or_external_clients(monkeypatch):
    from redis.asyncio import Redis

    from app.services.account_deletion_purge import PurgeStorage

    forbidden = AsyncMock(side_effect=AssertionError("external operation forbidden"))
    monkeypatch.setattr(cli, "recover_one", forbidden)
    monkeypatch.setattr(Redis, "from_url", lambda *_a, **_k: pytest.fail("Redis client forbidden"))
    monkeypatch.setattr(PurgeStorage, "__init__", lambda *_a, **_k: pytest.fail("S3 forbidden"))
    async with async_session_factory() as session:
        before = await session.scalar(text("SELECT count(*) FROM account_deletions"))
    assert await cli.run(cli.parser().parse_args(["--dry-run", "--limit", "10"])) == 0
    async with async_session_factory() as session:
        assert await session.scalar(text("SELECT count(*) FROM account_deletions")) == before
    forbidden.assert_not_called()


async def test_exception_during_actual_scan_releases_lock(monkeypatch):
    async with async_session_factory() as session:
        original = session.execute

        async def execute(statement, *args, **kwargs):
            if "FROM account_deletions" in str(statement):
                assert not await can_lock()
                raise RuntimeError("synthetic scan failure")
            return await original(statement, *args, **kwargs)

        monkeypatch.setattr(session, "execute", execute)
        with pytest.raises(RuntimeError):
            await audit_recovery(session, acquire_lock=True)
        assert not session.in_transaction()
    assert await can_lock()


async def test_process_termination_releases_transaction_lock():
    code = """
import asyncio
from app.db.session import engine
from app.services.account_deletion_recovery import begin_readonly, acquire_reconciliation_lock
async def main():
    async with engine.connect() as connection:
        await begin_readonly(connection)
        await acquire_reconciliation_lock(connection)
        print('LOCKED', flush=True)
        await asyncio.Event().wait()
asyncio.run(main())
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        code,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        assert await asyncio.wait_for(process.stdout.readline(), 10) == b"LOCKED\n"
        assert not await can_lock()
        process.terminate()
        await asyncio.wait_for(process.wait(), 5)
        assert await can_lock()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def test_nonzero_completion_is_aggregate_only(monkeypatch, capsys):
    from uuid import uuid4

    did = str(uuid4())
    audit = {
        "event": "account_deletion_recovery_audit",
        "requests": [{"deletion_id": did}],
        "overdue_incomplete": 3,
        "review_requests": 2,
        "eligible_ids": [did],
    }
    monkeypatch.setattr(cli, "audit_recovery", AsyncMock(return_value=audit))
    assert await cli.run(cli.parser().parse_args([])) == 0
    output = events(capsys)
    assert names(output) == ["started", "account_deletion_recovery_audit", "completed"]
    completed = output[-1]
    assert completed["examined_count"] == 1
    assert completed["overdue_count"] == 3
    assert completed["review_required_count"] == 2
    assert completed["stranded_candidate_count"] == 1
    assert did not in json.dumps(completed)


async def test_real_ledger_unchanged_and_nonzero_telemetry(case, capsys):
    did = await workflow.erase(case)

    async def snapshot():
        async with async_session_factory() as session:
            request = await session.scalar(
                text("SELECT to_jsonb(d) FROM account_deletions d WHERE id = :id"), {"id": did}
            )
            items = (
                (
                    await session.execute(
                        text(
                            "SELECT to_jsonb(i) FROM account_deletion_items i "
                            "WHERE deletion_id = :id ORDER BY id"
                        ),
                        {"id": did},
                    )
                )
                .scalars()
                .all()
            )
            return request, items

    before = await snapshot()
    assert await cli.run(cli.parser().parse_args(["--deletion-id", str(did)])) == 0
    assert await snapshot() == before
    assert case.storage.deleted == []
    completed = events(capsys)[-1]
    assert completed["event"] == "account_deletion_reconciliation.completed"
    assert completed["examined_count"] == 1
    for private in (str(case.uid), str(did), case.key, case.settings.s3_documents_bucket):
        assert private not in json.dumps(completed)
