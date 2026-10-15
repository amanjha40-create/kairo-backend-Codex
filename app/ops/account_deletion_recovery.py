"""Read-only by default. --execute recovers bounded existing incomplete work."""

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from uuid import UUID

from app.services.account_deletion_recovery import (
    LOCK_ID as LOCK_ID,
)
from app.services.account_deletion_recovery import (
    ReconciliationOverlap,
    RecoveryRefused,
    acquire_reconciliation_lock,
    audit_recovery,
    begin_readonly,
    recover_one,
    release_storage_review,
    validate_bounds,
)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    mode = result.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    result.add_argument("--limit", type=int, default=1)
    result.add_argument("--older-than", type=int, default=0, help="seconds past next-attempt time")
    result.add_argument("--deletion-id", type=UUID)
    result.add_argument(
        "--release-storage-review",
        action="store_true",
        help="release only after independently reviewed storage repair; no purge",
    )
    result.add_argument("--review-ticket", type=UUID, help="opaque approved incident ID, never PII")
    return result


def emit(value):
    print(json.dumps(value), flush=True)


async def run(args):
    started = time.monotonic()
    outcome = {}
    if not args.execute:
        reconciliation_event("started", limit=args.limit, older_than_seconds=args.older_than)
    try:
        code = await _run(args, outcome)
    except BaseException as error:
        if not args.execute:
            reconciliation_event("failed", category=failure_category(error), **duration(started))
        raise
    if not args.execute:
        if outcome.get("overlap"):
            reconciliation_event("skipped_overlap", **duration(started))
        else:
            audit = outcome["audit"]
            reconciliation_event(
                "completed",
                examined_count=len(audit["requests"]),
                overdue_count=audit["overdue_incomplete"],
                review_required_count=audit["review_requests"],
                stranded_count=None,
                stranded_count_basis="queue_presence_not_inferred_from_ledger",
                stranded_candidate_count=len(audit["eligible_ids"]),
                **duration(started),
            )
    return code


def duration(started):
    return {"duration_ms": max(0, round((time.monotonic() - started) * 1000))}


def reconciliation_event(name, **fields):
    emit(
        {
            "event": "account_deletion_reconciliation." + name,
            "dry_run": True,
            "timestamp": datetime.now(UTC).isoformat(),
            **fields,
        }
    )


def failure_category(error):
    if isinstance(error, (KeyboardInterrupt, asyncio.CancelledError)):
        return "interrupted"
    if isinstance(error, TimeoutError):
        return "time_budget_exhausted"
    if isinstance(error, RecoveryRefused):
        # Never copy exception text, even from an unexpected refusal subtype.
        return "reconciliation_refused"
    return "recovery_failed_inspect_safe_ledger"


async def _run(args, outcome):
    from redis.asyncio import Redis

    from app.config import get_settings
    from app.db.session import async_session_factory, engine

    try:
        validate_bounds(args.limit, args.older_than)
        settings = get_settings()
        if engine.echo:
            raise RecoveryRefused("sql_echo_must_be_disabled")
        if args.release_storage_review and not (
            args.execute and args.deletion_id and args.review_ticket and args.limit == 1
        ):
            raise RecoveryRefused("explicit_single_review_required")
        if args.review_ticket and not args.release_storage_review:
            raise RecoveryRefused("review_mode_required")
        if not args.execute:
            try:
                async with async_session_factory() as session:
                    audit = await audit_recovery(
                        session,
                        limit=args.limit,
                        older_than=args.older_than,
                        deletion_id=args.deletion_id,
                        acquire_lock=True,
                    )
            except ReconciliationOverlap:
                outcome["overlap"] = True
                return 0
            emit(audit)
            outcome["audit"] = audit
            return 0
        async with engine.connect() as lock:
            try:
                # The lock transaction never commits; recovery's existing per-record
                # transactions remain independent and keep their original semantics.
                await begin_readonly(lock)
                await acquire_reconciliation_lock(lock)
                async with async_session_factory() as session:
                    audit = await audit_recovery(
                        session,
                        limit=args.limit,
                        older_than=args.older_than,
                        deletion_id=args.deletion_id,
                    )
                emit(audit)
                if args.release_storage_review:
                    async with async_session_factory() as session:
                        emit(
                            await release_storage_review(
                                session, settings, args.deletion_id, args.review_ticket
                            )
                        )
                    return 0
                if args.deletion_id and str(args.deletion_id) not in audit["eligible_ids"]:
                    raise RecoveryRefused("target_not_eligible")
                async with Redis.from_url(settings.redis_url) as redis:
                    for value in audit["eligible_ids"]:
                        async with async_session_factory() as session:
                            result = await recover_one(session, settings, redis, UUID(value))
                        emit(
                            {
                                "event": "account_deletion_recovery_result",
                                "deletion_id": value,
                                **result,
                            }
                        )
                        if result["review"] or result["last_error_category"]:
                            return 2
                return 2 if audit["review_requests"] and not args.deletion_id else 0
            finally:
                await lock.rollback()
    finally:
        await engine.dispose()


async def bounded_run(args):
    async with asyncio.timeout(300):
        return await run(args)


def main():
    args = parser().parse_args()
    try:
        code = asyncio.run(bounded_run(args))
    except BaseException as error:
        if isinstance(error, (KeyboardInterrupt, asyncio.CancelledError)):
            category = "interrupted"
        elif isinstance(error, TimeoutError):
            category = "time_budget_exhausted"
        elif isinstance(error, RecoveryRefused):
            category = str(error)
        else:
            category = "recovery_failed_inspect_safe_ledger"
        emit({"event": "account_deletion_recovery_failed", "category": category})
        code = 2
    raise SystemExit(code)


if __name__ == "__main__":
    main()
