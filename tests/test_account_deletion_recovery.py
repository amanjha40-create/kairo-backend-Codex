"""Synthetic local DB, mocked storage/queue; no real recipient or AWS actions."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
import test_account_deletion_workflow as workflow
from sqlalchemy import delete, func, select, text, update

from app.db.session import async_session_factory
from app.models.account_deletion import AccountDeletion, AccountDeletionItem
from app.models.admin_access_audit_event import AdminAccessAuditEvent
from app.ops.account_deletion_recovery import parser
from app.services.account_deletion_purge import UnsafeReference
from app.services.account_deletion_recovery import (
    RELEASE_ACTION,
    RecoveryRefused,
    audit_recovery,
    recover_one,
    release_storage_review,
    validate_bounds,
)

case = workflow.case
erase = workflow.erase
item_for = workflow.item_for


async def audit(deletion_id=None, **kwargs):
    async with async_session_factory() as session:
        return await audit_recovery(session, deletion_id=deletion_id, **kwargs)


async def recover(case, deletion_id, hours=2):
    async with async_session_factory() as session:
        return await recover_one(
            session,
            case.settings,
            case.redis,
            deletion_id,
            storage=case.storage,
            now=datetime.now(UTC) + timedelta(hours=hours),
        )


@pytest.fixture
async def review_case(case):
    yield case
    async with async_session_factory() as session:
        ids = select(AccountDeletion.id).where(AccountDeletion.user_id == case.uid)
        for value in (await session.scalars(ids)).all():
            await session.execute(
                delete(AdminAccessAuditEvent).where(
                    AdminAccessAuditEvent.action == RELEASE_ACTION,
                    AdminAccessAuditEvent.metadata_payload["deletion_id"].astext == str(value),
                )
            )
        await session.commit()


async def set_review(case, deletion_id, category="storage_permission_or_configuration"):
    async with async_session_factory() as session:
        await session.execute(
            update(AccountDeletion)
            .where(AccountDeletion.id == deletion_id)
            .values(
                status="operator_review",
                next_attempt_at=datetime.now(UTC) - timedelta(minutes=1),
                last_error_category=category,
            )
        )
        await session.execute(
            update(AccountDeletionItem)
            .where(
                AccountDeletionItem.deletion_id == deletion_id, AccountDeletionItem.kind == "object"
            )
            .values(status="review", last_error_category=category)
        )
        await session.commit()


async def test_readonly_audit_due_counts_and_privacy(case):
    did = await erase(case)
    before = await item_for(case, case.key)
    result = await audit(did, now=datetime.now(UTC) + timedelta(hours=2))
    assert result["eligible_ids"] == [str(did)]
    assert result["read_only"] and result["overdue_incomplete"] >= 1
    serialized = json.dumps(result)
    for private in (str(case.uid), case.key, case.other_key, case.settings.s3_documents_bucket):
        assert private not in serialized
    assert (await item_for(case, case.key)).attempts == before.attempts
    assert case.storage.deleted == []


async def test_not_due_and_complete_excluded(case):
    did = await erase(case)
    assert (await audit(did))["eligible_ids"] == []
    with pytest.raises(RecoveryRefused):
        await recover(case, did, hours=0)
    assert (await recover(case, did))["status"] == "complete"
    assert (await audit(did, now=datetime.now(UTC) + timedelta(days=2)))["eligible_ids"] == []
    deleted = list(case.storage.deleted)
    with pytest.raises(RecoveryRefused):
        await recover(case, did, hours=48)
    assert case.storage.deleted == deleted


async def test_older_than_filter_and_bounded_candidates(case):
    did = await erase(case)
    now = datetime.now(UTC) + timedelta(hours=2)
    assert (await audit(did, now=now, older_than=86400))["eligible_ids"] == []
    assert len((await audit(did, now=now, limit=1))["eligible_ids"]) == 1


@pytest.mark.parametrize("limit,age", [(0, 0), (11, 0), (1, -1), (1, 604801)])
def test_bounds(limit, age):
    with pytest.raises(RecoveryRefused):
        validate_bounds(limit, age)


def test_cli_defaults_and_explicit_execute():
    assert not parser().parse_args([]).execute
    assert not parser().parse_args(["--dry-run"]).execute
    assert parser().parse_args(["--execute"]).execute
    with pytest.raises(SystemExit):
        parser().parse_args(["--execute", "--dry-run"])
    with pytest.raises(SystemExit):
        parser().parse_args(["--deletion-id", "malformed"])


async def test_manual_release_atomic_audited_and_idempotent(review_case, caplog):
    case = review_case
    did, ticket = await erase(case), uuid4()
    await set_review(case, did)
    assert (await audit(did, now=datetime.now(UTC) + timedelta(hours=4)))["eligible_ids"] == []
    for expected in ("released", "already_recorded"):
        async with async_session_factory() as session:
            result = await release_storage_review(session, case.settings, did, ticket)
        assert result["result"] == expected
    assert case.storage.deleted == []
    async with async_session_factory() as session:
        events = list(
            (
                await session.scalars(
                    select(AdminAccessAuditEvent).where(
                        AdminAccessAuditEvent.action == RELEASE_ACTION,
                        AdminAccessAuditEvent.metadata_payload["deletion_id"].astext == str(did),
                    )
                )
            ).all()
        )
        assert len(events) == 1
        assert events[0].metadata_payload["review_ticket"] == str(ticket)
        assert events[0].actor_user_id is None and events[0].subject_user_id is None
        assert case.key not in json.dumps(events[0].metadata_payload)
    assert (await recover(case, did))["status"] == "complete"
    assert case.key not in caplog.text


@pytest.mark.parametrize(
    "category",
    [
        "ownership_or_configuration_guard",
        "unsafe_legacy_reference",
        "legacy_evidence_unresolved",
        "private raw reason",
    ],
)
async def test_non_storage_review_never_released(review_case, category):
    case = review_case
    did = await erase(case)
    await set_review(case, did, category)
    async with async_session_factory() as session:
        with pytest.raises(RecoveryRefused):
            await release_storage_review(session, case.settings, did, uuid4())
    assert (await item_for(case, case.key)).status == "review"
    assert category != "private raw reason" or category not in json.dumps(await audit(did))
    assert case.storage.deleted == []


async def test_review_commit_failure_does_not_release(review_case, monkeypatch):
    case = review_case
    did = await erase(case)
    await set_review(case, did)
    async with async_session_factory() as session:
        monkeypatch.setattr(session, "commit", AsyncMock(side_effect=RuntimeError("synthetic")))
        with pytest.raises(RuntimeError):
            await release_storage_review(session, case.settings, did, uuid4())
    assert (await item_for(case, case.key)).status == "review"
    async with async_session_factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AdminAccessAuditEvent)
                .where(
                    AdminAccessAuditEvent.action == RELEASE_ACTION,
                    AdminAccessAuditEvent.metadata_payload["deletion_id"].astext == str(did),
                )
            )
            == 0
        )


async def test_review_race_or_malformed_ledger_refused_before_storage(case):
    did = await erase(case)
    assert (await audit(did, now=datetime.now(UTC) + timedelta(hours=2)))["eligible_ids"]
    await set_review(case, did)
    with pytest.raises(RecoveryRefused):
        await recover(case, did)
    assert case.storage.deleted == []


async def test_mixed_review_request_is_refused_before_storage(case):
    did = await erase(case)
    await set_review(case, did)
    async with async_session_factory() as session:
        await session.execute(
            update(AccountDeletion).where(AccountDeletion.id == did).values(status="purge_partial")
        )
        await session.commit()
    with pytest.raises(UnsafeReference):
        await recover(case, did)
    assert case.storage.deleted == []


async def test_default_cli_is_readonly_and_execute_is_bounded(case, monkeypatch, capsys):
    from app.ops import account_deletion_recovery as cli

    did = await erase(case)
    mocked = AsyncMock()
    monkeypatch.setattr(cli, "recover_one", mocked)
    assert await cli.run(parser().parse_args([])) == 0
    mocked.assert_not_called()
    assert '"read_only": true' in capsys.readouterr().out
    async with async_session_factory() as session:
        await session.execute(
            update(AccountDeletion)
            .where(AccountDeletion.id == did)
            .values(next_attempt_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()
    mocked.return_value = {
        "status": "purge_pending",
        "pending": 1,
        "review": 0,
        "last_error_category": None,
    }
    assert await cli.run(parser().parse_args(["--execute", "--deletion-id", str(did)])) == 0
    mocked.assert_awaited_once()
    assert mocked.call_args.args[3] == did


async def test_default_cli_refuses_incomplete_release_approval(case):
    from app.ops import account_deletion_recovery as cli

    for arguments in (
        ["--release-storage-review"],
        ["--review-ticket", str(uuid4())],
        ["--execute", "--release-storage-review", "--deletion-id", str(uuid4())],
    ):
        with pytest.raises(RecoveryRefused):
            await cli.run(parser().parse_args(arguments))


async def test_unknown_deletion_payload_fails_sanitized():
    from app.workers.handlers.account_deletion import purge_account

    for data in ({}, {"deletion_id": "private-malformed-value"}):
        with pytest.raises(RuntimeError, match="^account_deletion_worker_failed$"):
            await purge_account(data, None)


async def test_audit_stops_when_read_only_cannot_be_confirmed():
    session = Mock()
    session.in_transaction.return_value = False
    session.execute = AsyncMock()
    session.scalar = AsyncMock(return_value="off")
    session.rollback = AsyncMock()
    with pytest.raises(RecoveryRefused, match="read_only_not_confirmed"):
        await audit_recovery(session)
    session.execute.assert_awaited_once()
    session.rollback.assert_awaited_once()


async def test_concurrent_operator_invocation_refused(case, monkeypatch):
    from app.db.session import engine
    from app.ops import account_deletion_recovery as cli

    mocked = AsyncMock()
    monkeypatch.setattr(cli, "recover_one", mocked)
    async with engine.connect() as connection:
        await connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": cli.LOCK_ID})
        await connection.commit()
        try:
            with pytest.raises(RecoveryRefused, match="another_recovery_running"):
                await cli.run(parser().parse_args(["--execute"]))
            mocked.assert_not_called()
        finally:
            await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": cli.LOCK_ID})
            await connection.commit()


def test_cli_error_output_never_contains_raw_exception(monkeypatch, capsys):
    from app.ops import account_deletion_recovery as cli

    monkeypatch.setattr("sys.argv", ["account_deletion_recovery"])
    monkeypatch.setattr(
        cli, "bounded_run", AsyncMock(side_effect=RuntimeError("private-bucket/key"))
    )
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 2
    output = capsys.readouterr().out
    assert "private-bucket/key" not in output
    assert "recovery_failed_inspect_safe_ledger" in output


async def test_recovery_missing_id_and_empty_ledger_fail_closed(case):
    with pytest.raises(RecoveryRefused):
        await recover(case, uuid4())
    did = await erase(case)
    async with async_session_factory() as session:
        await session.execute(
            delete(AccountDeletionItem).where(AccountDeletionItem.deletion_id == did)
        )
        await session.commit()
    with pytest.raises(UnsafeReference):
        await recover(case, did)
    assert case.storage.deleted == []


async def test_recovery_partial_external_delete_and_db_rollback(case, monkeypatch):
    did = await erase(case)
    async with async_session_factory() as session:
        monkeypatch.setattr(session, "commit", AsyncMock(side_effect=RuntimeError("synthetic")))
        with pytest.raises(RuntimeError):
            await recover_one(
                session,
                case.settings,
                case.redis,
                did,
                storage=case.storage,
                now=datetime.now(UTC) + timedelta(hours=2),
            )
    assert case.key not in case.storage.objects
    assert (await item_for(case, case.key)).status == "pending"
    assert (await recover(case, did))["status"] == "complete"


async def test_crash_claim_can_drop_queue_acceleration_but_recovery_finishes(case, monkeypatch):
    from app.workers import consumer

    did = await erase(case)
    claimed = set()

    async def claim(message_id):
        if message_id in claimed:
            return False
        claimed.add(message_id)
        return True

    async def handler(data, unused_session):
        await recover(case, did)

    monkeypatch.setattr(consumer, "_mark_processed", claim)
    monkeypatch.setattr(consumer, "get_handler", lambda _: handler)
    client = Mock()
    raw = {
        "MessageId": str(uuid4()),
        "ReceiptHandle": "synthetic",
        "Body": json.dumps({"type": "account.deletion.purge", "data": {"deletion_id": str(did)}}),
    }
    case.storage.crash = True
    with pytest.raises(asyncio.CancelledError):
        await consumer._process_message(client, "synthetic", raw)
    case.storage.crash = False
    await consumer._process_message(client, "synthetic", raw)
    client.delete_message.assert_called_once()
    assert (await item_for(case, case.key)).status == "pending"
    assert (await recover(case, did))["status"] == "complete"


async def test_poison_envelope_and_unknown_handler_are_not_acknowledged(monkeypatch):
    from app.workers import consumer

    client = Mock()
    monkeypatch.setattr(consumer, "get_handler", lambda _: None)
    for body in ("not-json", json.dumps({"type": "unknown", "data": {}})):
        await consumer._process_message(
            client,
            "synthetic",
            {
                "MessageId": "synthetic",
                "ReceiptHandle": "synthetic",
                "Body": body,
            },
        )
    client.delete_message.assert_not_called()
