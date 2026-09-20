"""Post-commit erasure driven by the database, independent of queue delivery."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from botocore.exceptions import ClientError
from sqlalchemy import select

from app.auth.signup_otp import SignupOtpStore
from app.infrastructure.s3.client import get_s3_client
from app.models.account_deletion import AccountDeletion, AccountDeletionItem
from app.models.user import User
from app.services.account_deletion_inventory import identity, safe_key

logger = logging.getLogger(__name__)


class UnsafeReference(Exception):
    """An ownership/configuration guard failed; never include the reference."""


class PurgeStorage:
    def __init__(self, settings):
        self.client = get_s3_client(settings)

    async def discover(self, bucket, prefix):
        page = await asyncio.to_thread(
            self.client.list_object_versions, Bucket=bucket, Prefix=prefix, MaxKeys=200
        )
        entries = page.get("Versions", []) + page.get("DeleteMarkers", [])
        return sorted({row["Key"] for row in entries}), bool(page.get("IsTruncated"))

    async def purge(self, bucket, key):
        # Remove every exact version, including delete markers; a simple DELETE
        # alone only hides bytes in versioned buckets. Never delete prefix siblings.
        for _ in range(20):
            page = await asyncio.to_thread(
                self.client.list_object_versions, Bucket=bucket, Prefix=key, MaxKeys=1000
            )
            entries = [
                row
                for row in page.get("Versions", []) + page.get("DeleteMarkers", [])
                if row["Key"] == key
            ]
            if not entries:
                return
            for row in entries:
                try:
                    await asyncio.to_thread(
                        self.client.delete_object,
                        Bucket=bucket,
                        Key=key,
                        VersionId=row["VersionId"],
                    )
                except ClientError as error:
                    if error.response.get("Error", {}).get("Code") not in {
                        "NoSuchKey",
                        "NoSuchVersion",
                    }:
                        raise
        raise TimeoutError("purge_batch_limit")


def failure_category(error):
    if isinstance(error, UnsafeReference):
        return "ownership_or_configuration_guard", True
    if isinstance(error, ClientError):
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code in {"AccessDenied", "InvalidAccessKeyId", "InvalidBucketName", "NoSuchBucket"}:
            return "storage_permission_or_configuration", True
    return "cleanup_temporarily_unavailable", False


def permitted_scope(request, item):
    prefix, uid = request.storage_prefix, request.user_id
    scopes = {
        "resume": f"resumes/{uid}/",
        "vault": f"{prefix}/user-documents/{uid}/",
        "employment": f"{prefix}/users/{uid}/employments/",
        "internship": f"{prefix}/users/{uid}/internships/",
        "freelance": f"{prefix}/users/{uid}/freelance/",
        "certification": f"{prefix}/certifications/{uid}/",
        "portfolio": f"{prefix}/portfolio/{uid}/",
        "avatar": f"{prefix}/users/{uid}/avatar.",
    }
    scope = item.scope_prefix
    if item.source_type in {"education", "pack_snapshot"}:
        stem = "education-documents" if item.source_type == "education" else "document-share-packs"
        start = f"{prefix}/{stem}/"
        if not scope or not scope.startswith(start) or not scope.endswith("/"):
            return False
        try:
            return str(UUID(scope[len(start) : -1])) == scope[len(start) : -1]
        except ValueError:
            return False
    return scope == scopes.get(item.source_type)


def assert_owned_reference(request, item):
    if not (
        safe_key(item.object_key)
        and safe_key(item.scope_prefix)
        and permitted_scope(request, item)
        and item.object_key.startswith(item.scope_prefix)
    ):
        raise UnsafeReference()
    if item.kind == "namespace" and item.object_key != item.scope_prefix:
        raise UnsafeReference()
    if item.source_type == "avatar" and item.object_key.removeprefix(item.scope_prefix) not in {
        "jpg",
        "jpeg",
        "png",
        "webp",
    }:
        raise UnsafeReference()


async def sweep_deletions(session, settings, redis, *, storage=None, deletion_id=None, now=None):
    """Process one committed request. Caller must supply a fresh session.

    Row locks serialize duplicate deliveries. New discoveries are committed as
    ledger entries *before* a later sweep can delete their bytes. Crashes roll back
    bookkeeping, never the already committed logical deletion.
    """
    if session.in_transaction():
        raise RuntimeError("Deletion purge requires a fresh post-commit session")
    now = now or datetime.now(UTC)
    try:
        query = select(AccountDeletion).where(AccountDeletion.next_attempt_at <= now)
        if deletion_id is not None:
            query = query.where(AccountDeletion.id == deletion_id)
        request = await session.scalar(
            query.order_by(AccountDeletion.next_attempt_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if request is None:
            await session.rollback()
            return None
        owner = await session.get(User, request.user_id)
        owner_erased = owner is None or (owner.deleted_at is not None and not owner.is_active)
        items = list(
            (
                await session.scalars(
                    select(AccountDeletionItem).where(AccountDeletionItem.deletion_id == request.id)
                )
            ).all()
        )
        by_hash = {item.identity_hash: item for item in items}
        request.purge_started_at = request.purge_started_at or now
        request.last_error_category = None
        # Construct S3 lazily: OTP-only work and guarded malformed references need none.
        active_storage = storage
        processed = 0
        for item in sorted(items, key=lambda entry: entry.kind == "namespace"):
            if item.status == "review" or item.next_attempt_at > now:
                continue
            if item.status == "complete" and item.kind != "namespace":
                continue
            if processed >= 250:
                break
            processed += 1
            item.attempts += 1
            try:
                if not owner_erased:
                    raise UnsafeReference()
                if item.kind == "otp":
                    await SignupOtpStore(redis, settings).clear_all(item.source_id)
                else:
                    assert_owned_reference(request, item)
                    if (
                        not request.storage_bucket
                        or request.storage_bucket != settings.s3_documents_bucket
                    ):
                        raise UnsafeReference()
                    active_storage = active_storage or PurgeStorage(settings)
                    if item.kind == "object":
                        await active_storage.purge(request.storage_bucket, item.object_key)
                    elif item.kind == "namespace":
                        keys, truncated = await active_storage.discover(
                            request.storage_bucket, item.scope_prefix
                        )
                        for key in keys:
                            probe = AccountDeletionItem(
                                kind="object",
                                object_key=key,
                                source_type=item.source_type,
                                scope_prefix=item.scope_prefix,
                            )
                            assert_owned_reference(request, probe)
                            fingerprint = identity("object", key)
                            previous = by_hash.get(fingerprint)
                            if previous is None:
                                previous = AccountDeletionItem(
                                    deletion_id=request.id,
                                    identity_hash=fingerprint,
                                    kind="object",
                                    source_type=item.source_type,
                                    object_key=key,
                                    scope_prefix=item.scope_prefix,
                                    status="pending",
                                    next_attempt_at=now,
                                    attempts=0,
                                )
                                session.add(previous)
                                by_hash[fingerprint] = previous
                            elif previous.status == "complete":
                                previous.status = "pending"
                                previous.object_key = key
                                previous.completed_at = None
                                previous.next_attempt_at = now
                        if truncated:
                            item.status, item.next_attempt_at = (
                                "pending",
                                now + timedelta(seconds=5),
                            )
                            continue
                    else:
                        raise UnsafeReference()
                item.status, item.completed_at, item.last_error_category = "complete", now, None
                if item.kind == "object":
                    item.object_key = None  # Keep only the hashed non-content tombstone.
                if item.kind == "namespace":
                    # Old presigned PUTs can finish late. Reconcile only proven owned
                    # namespaces, even after completion, without a bucket-wide scan.
                    item.next_attempt_at = now + timedelta(hours=1)
            except Exception as error:
                category, permanent = failure_category(error)
                item.status = "review" if permanent else "retry"
                item.last_error_category = category
                item.next_attempt_at = now + timedelta(
                    seconds=min(3600, 30 * 2 ** min(item.attempts, 7))
                )
                request.retry_count += 1
                request.last_error_category = category
        states = list(by_hash.values())
        unfinished = [row for row in states if row.status in {"pending", "retry"}]
        review = any(row.status == "review" for row in states)
        request.last_error_category = next(
            (
                row.last_error_category
                for row in states
                if row.status in {"retry", "review"} and row.last_error_category
            ),
            None,
        )
        request.status = (
            ("purge_partial" if request.retry_count else "purge_pending")
            if unfinished
            else ("operator_review" if review else "complete")
        )
        request.completed_at = now if request.status == "complete" else None
        due = [
            row.next_attempt_at
            for row in states
            if row.status in {"pending", "retry"}
            or (row.kind == "namespace" and row.status == "complete")
        ]
        request.next_attempt_at = (
            max(now + timedelta(seconds=1), min(due)) if due else now + timedelta(days=1)
        )
        summary = {
            "status": request.status,
            "pending": len(unfinished),
            "success": sum(row.status == "complete" for row in states),
            "review": sum(row.status == "review" for row in states),
            "retry_count": request.retry_count,
            "last_error_category": request.last_error_category,
        }
        await session.commit()
        logger.info("account_deletion.purge_progress", extra=summary)
        return summary
    except BaseException:
        await session.rollback()
        raise
