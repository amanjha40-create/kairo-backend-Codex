"""Bounded operator recovery of existing erasure intent, never new deletion intent."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, text

from app.models.account_deletion import AccountDeletion, AccountDeletionItem
from app.models.admin_access_audit_event import AdminAccessAuditEvent
from app.models.user import User
from app.services.account_deletion_purge import assert_owned_reference, sweep_deletions

RETRYABLE = ("purge_pending", "purge_partial")
CATEGORIES = {
    "storage_permission_or_configuration",
    "ownership_or_configuration_guard",
    "cleanup_temporarily_unavailable",
    "unsafe_legacy_reference",
    "legacy_evidence_unresolved",
}
RELEASE_ACTION = "account_deletion_storage_review_released"
# Reserved recovery namespace from the original operator CLI (0x4B414D452C99454C).
# Retain the identity so older session-lock operators also exclude new dry-runs.
LOCK_ID = 5422700385827112268


class RecoveryRefused(Exception):
    """Only fixed, non-sensitive reason codes may cross the CLI boundary."""


class ReconciliationOverlap(RecoveryRefused):
    """A competing reconciliation/recovery owns the shared lock."""


async def begin_readonly(session):
    await session.execute(text("SET TRANSACTION READ ONLY"))
    if await session.scalar(text("SHOW transaction_read_only")) != "on":
        raise RecoveryRefused("read_only_not_confirmed")
    await session.execute(text("SET LOCAL statement_timeout = '5s'"))
    await session.execute(text("SET LOCAL lock_timeout = '2s'"))


async def acquire_reconciliation_lock(session):
    if not await session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": LOCK_ID}):
        raise ReconciliationOverlap("another_recovery_running")


def safe_category(value):
    return value if value in CATEGORIES else "unclassified" if value else "none"


def validate_bounds(limit, older_than):
    if not 1 <= limit <= 10 or not 0 <= older_than <= 604800:
        raise RecoveryRefused("invalid_bounds")


async def audit_recovery(
    session, *, limit=1, older_than=0, deletion_id=None, now=None, acquire_lock=False
):
    validate_bounds(limit, older_than)
    if session.in_transaction():
        raise RecoveryRefused("fresh_session_required")
    now = now or datetime.now(UTC)
    try:
        await begin_readonly(session)
        if acquire_lock:
            await acquire_reconciliation_lock(session)
        statuses = dict(
            (
                await session.execute(
                    select(AccountDeletion.status, func.count()).group_by(AccountDeletion.status)
                )
            ).all()
        )
        cutoff = now - timedelta(seconds=older_than)
        due = AccountDeletion.next_attempt_at <= cutoff
        overdue = await session.scalar(
            select(func.count())
            .select_from(AccountDeletion)
            .where(AccountDeletion.status != "complete", AccountDeletion.next_attempt_at <= now)
        )
        review_count = await session.scalar(
            select(func.count(func.distinct(AccountDeletionItem.deletion_id))).where(
                AccountDeletionItem.status == "review"
            )
        )
        query = select(AccountDeletion).where(AccountDeletion.status != "complete")
        if deletion_id is not None:
            query = query.where(AccountDeletion.id == deletion_id)
        rows = list(
            (
                await session.scalars(
                    query.order_by(AccountDeletion.next_attempt_at, AccountDeletion.id).limit(limit)
                )
            ).all()
        )
        candidates = select(AccountDeletion.id).where(
            AccountDeletion.status.in_(RETRYABLE),
            due,
            ~select(AccountDeletionItem.id)
            .where(
                AccountDeletionItem.deletion_id == AccountDeletion.id,
                AccountDeletionItem.status == "review",
            )
            .exists(),
        )
        if deletion_id is not None:
            candidates = candidates.where(AccountDeletion.id == deletion_id)
        ids = list(
            (
                await session.scalars(
                    candidates.order_by(AccountDeletion.next_attempt_at, AccountDeletion.id).limit(
                        limit
                    )
                )
            ).all()
        )
        item_totals = {}
        for deletion, status, count, attempts in (
            await session.execute(
                select(
                    AccountDeletionItem.deletion_id,
                    AccountDeletionItem.status,
                    func.count(),
                    func.sum(AccountDeletionItem.attempts),
                )
                .where(AccountDeletionItem.deletion_id.in_([row.id for row in rows]))
                .group_by(AccountDeletionItem.deletion_id, AccountDeletionItem.status)
            )
        ).all():
            summary = item_totals.setdefault(deletion, {"attempts": 0, "states": {}})
            summary["states"][status] = count
            summary["attempts"] += attempts
        return {
            "event": "account_deletion_recovery_audit",
            "read_only": True,
            "counts": statuses,
            "overdue_incomplete": overdue,
            "review_requests": review_count,
            "eligible_ids": [str(value) for value in ids],
            "queue_presence": "not_inferred_from_ledger",
            "running": "not_durably_recorded",
            "requests": [
                {
                    "deletion_id": str(row.id),
                    "status": row.status,
                    "due": row.next_attempt_at <= now,
                    "retry_count": row.retry_count,
                    "items": item_totals.get(row.id, {"attempts": 0, "states": {}}),
                    "requested_at": row.requested_at.isoformat(),
                    "db_committed_at": row.db_committed_at.isoformat(),
                    "first_purge_started_at": row.purge_started_at.isoformat()
                    if row.purge_started_at
                    else None,
                    "failure_category": safe_category(row.last_error_category),
                    "age_bucket": "over_24h"
                    if now - row.requested_at >= timedelta(days=1)
                    else "over_1h"
                    if now - row.requested_at >= timedelta(hours=1)
                    else "under_1h",
                    "next_attempt_at": row.next_attempt_at.isoformat(),
                    "last_ledger_update": row.updated_at.isoformat(),
                    "recommended_action": "manual_review"
                    if row.status == "operator_review"
                    or item_totals.get(row.id, {}).get("states", {}).get("review", 0)
                    else "inspect_then_recover_when_due",
                }
                for row in rows
            ],
        }
    finally:
        await session.rollback()


async def release_storage_review(session, settings, deletion_id, review_ticket, *, now=None):
    """One reviewed incident, one exact request, atomic release plus existing audit table."""
    if not isinstance(deletion_id, UUID) or not isinstance(review_ticket, UUID):
        raise RecoveryRefused("uuid_required")
    if session.in_transaction():
        raise RecoveryRefused("fresh_session_required")
    now = now or datetime.now(UTC)
    try:
        await session.execute(text("SET LOCAL lock_timeout = '2s'"))
        request = await session.scalar(
            select(AccountDeletion).where(AccountDeletion.id == deletion_id).with_for_update()
        )
        if request is None or request.status == "complete":
            raise RecoveryRefused("missing_or_complete")
        prior = await session.scalar(
            select(AdminAccessAuditEvent.id)
            .where(
                AdminAccessAuditEvent.action == RELEASE_ACTION,
                AdminAccessAuditEvent.metadata_payload["review_ticket"].astext
                == str(review_ticket),
                AdminAccessAuditEvent.metadata_payload["deletion_id"].astext == str(deletion_id),
            )
            .limit(1)
        )
        if prior is not None:
            await session.rollback()
            return {"event": "account_deletion_review_release", "result": "already_recorded"}
        if request.next_attempt_at > now:
            raise RecoveryRefused("not_due")
        owner = await session.get(User, request.user_id)
        if owner is not None and (owner.deleted_at is None or owner.is_active):
            raise RecoveryRefused("owner_not_erased")
        items = list(
            (
                await session.scalars(
                    select(AccountDeletionItem).where(
                        AccountDeletionItem.deletion_id == deletion_id
                    )
                )
            ).all()
        )
        review = [item for item in items if item.status == "review"]
        if not review or request.status not in (*RETRYABLE, "operator_review"):
            raise RecoveryRefused("no_releasable_review")
        if not request.storage_bucket or request.storage_bucket != settings.s3_documents_bucket:
            raise RecoveryRefused("storage_configuration_guard")
        for item in items:
            if item.status == "complete":
                continue
            if item.kind == "otp" and item.status != "review" and isinstance(item.source_id, UUID):
                continue
            if item.kind not in {"object", "namespace"}:
                raise RecoveryRefused("unresolved_reference")
            assert_owned_reference(request, item)
            if (
                item.status == "review"
                and item.last_error_category != "storage_permission_or_configuration"
            ):
                raise RecoveryRefused("non_storage_review")
        session.add(
            AdminAccessAuditEvent(
                action=RELEASE_ACTION,
                actor_role="operator",
                summary="Explicit reviewed storage recovery; no purge performed by release",
                metadata_payload={
                    "deletion_id": str(deletion_id),
                    "review_ticket": str(review_ticket),
                    "released_items": len(review),
                    "prior_status": request.status,
                    "failure_category": "storage_permission_or_configuration",
                    "prior_attempts": sum(item.attempts for item in review),
                },
            )
        )
        for item in review:
            item.status, item.next_attempt_at = "retry", now
        request.status, request.next_attempt_at = "purge_partial", now
        await session.commit()
        return {
            "event": "account_deletion_review_release",
            "result": "released",
            "deletion_id": str(deletion_id),
            "review_ticket": str(review_ticket),
            "released_items": len(review),
        }
    except BaseException:
        await session.rollback()
        raise


async def recover_one(session, settings, redis, deletion_id, *, storage=None, now=None):
    result = await sweep_deletions(
        session,
        settings,
        redis,
        deletion_id=deletion_id,
        storage=storage,
        now=now,
        recovery_only=True,
    )
    if result is None:
        raise RecoveryRefused("not_due_complete_or_locked")
    return result
