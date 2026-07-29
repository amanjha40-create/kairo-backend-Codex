#!/usr/bin/env python3
"""QA-only destructive reset utility for local Docker and staging.

This module intentionally has no HTTP entry point.  It is executable only in
development, test, or staging environments and refuses production settings.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Table, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

# Allow `python scripts/reset_test_data.py ...` to resolve the repository's
# application package without requiring installation as a site package.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Keep the production refusal ahead of application imports. This prevents a
# malformed production environment from turning a safety refusal into startup
# or database configuration work.
if __name__ == "__main__" and os.getenv("APP_ENV", "").strip().lower() == "production":
    print("reset refused: QA reset is forbidden when APP_ENV=production", file=sys.stderr)
    raise SystemExit(2)

from app.auth.email_utils import normalize_email
from app.config import get_settings
from app.config.settings import AppEnvironment
from app.db.base import Base
from app.db.session import async_session_factory
from app.models import Organization, OrganizationMember, PendingSignup, User


class ResetSafetyError(RuntimeError):
    """Raised when a reset would cross an ownership or environment boundary."""


@dataclass(frozen=True)
class ResetMode:
    emails: tuple[str, ...] = ()
    full_reset: bool = False
    dry_run: bool = False


@dataclass
class ResetResult:
    counts: dict[str, int]
    pending_signup_ids: tuple[UUID, ...] = ()
    storage_objects: tuple[tuple[str, str], ...] = ()


# These names represent ownership, rather than an actor/audit reference.
OWNER_COLUMNS = frozenset(
    {
        "user_id",
        "owner_user_id",
        "profile_user_id",
        "subject_user_id",
        "recipient_user_id",
        "invitee_user_id",
        "completed_user_id",
        # Candidate-owned records such as employment and trust invitations
        # use a creator column rather than a user_id column.
        "created_by_user_id",
    }
)
ACTOR_COLUMNS = frozenset(
    {
        "created_by_user_id",
        "updated_by_user_id",
        "deleted_by_user_id",
        "reviewed_by_user_id",
        "assigned_reviewer_user_id",
        "requested_by_user_id",
        "resolved_by_user_id",
        "verified_by_user_id",
        "submitted_by_user_id",
        "uploaded_by_user_id",
        "invited_by_user_id",
        "accepted_by_user_id",
        "added_by_user_id",
        "author_user_id",
        "actor_user_id",
        "status_changed_by_user_id",
        "decision_by_user_id",
        "assigned_by_user_id",
        "revoked_by_user_id",
        "merged_by_user_id",
        "registry_resolved_by_user_id",
    }
)
OBJECT_COLUMNS = frozenset({"object_key", "storage_key", "avatar_key", "s3_key", "file_key"})


def normalize_emails(values: Iterable[str]) -> tuple[str, ...]:
    """Normalize and deduplicate explicitly supplied email addresses."""

    normalized = {normalize_email(value) for value in values if value.strip()}
    if not normalized:
        raise ValueError("At least one email address is required")
    return tuple(sorted(normalized))


def validate_environment(*, app_env: AppEnvironment, full_reset: bool) -> None:
    """Fail closed outside permitted QA environments."""

    if app_env == AppEnvironment.PRODUCTION:
        raise ResetSafetyError("QA reset is forbidden when APP_ENV=production")
    if app_env not in {AppEnvironment.DEVELOPMENT, AppEnvironment.TEST, AppEnvironment.STAGING}:
        raise ResetSafetyError(f"QA reset is not supported for APP_ENV={app_env}")
    if full_reset and app_env != AppEnvironment.STAGING:
        raise ResetSafetyError("--full-reset is allowed only when APP_ENV=staging")


def parse_mode(*, email: str | None, emails_file: str | None, full_reset: bool) -> ResetMode:
    """Validate mutually exclusive CLI modes without touching the database."""

    selected = sum(value is not None for value in (email, emails_file)) + int(full_reset)
    if selected != 1:
        raise ValueError("Choose exactly one of --email, --emails, or --full-reset")
    if email is not None:
        return ResetMode(emails=normalize_emails([email]))
    if emails_file is not None:
        path = Path(emails_file)
        if not path.is_file():
            raise ValueError(f"Email list does not exist: {path}")
        return ResetMode(emails=normalize_emails(path.read_text(encoding="utf-8").splitlines()))
    return ResetMode(full_reset=True)


def confirm_full_reset(*, confirmed: bool, interactive_input: str | None = None) -> None:
    """Require an explicit, unambiguous full-reset confirmation."""

    if confirmed or interactive_input == "FULL STAGING RESET":
        return
    raise ResetSafetyError(
        "Full reset requires --confirm-full-reset or typing 'FULL STAGING RESET'"
    )


def _table_depths(metadata: Any) -> dict[str, int]:
    """Return child-before-parent ordering for metadata tables."""

    children: dict[str, set[str]] = defaultdict(set)
    for table in metadata.tables.values():
        for constraint in table.foreign_key_constraints:
            for element in constraint.elements:
                if element.column.table.name in metadata.tables:
                    parent = element.column.table.name
                    children[parent].add(table.name)

    memo: dict[str, int] = {}

    def depth(name: str, visiting: set[str]) -> int:
        if name in memo:
            return memo[name]
        if name in visiting:
            return 0
        visiting.add(name)
        value = 0
        for child in children.get(name, set()):
            value = max(value, depth(child, visiting) + 1)
        visiting.remove(name)
        memo[name] = value
        return value

    return {table.name: depth(table.name, set()) for table in metadata.tables.values()}


def _user_foreign_keys(table: Table) -> list[tuple[Any, str]]:
    refs: list[tuple[Any, str]] = []
    for constraint in table.foreign_key_constraints:
        for element in constraint.elements:
            if element.column.table.name == "users":
                refs.append((element.parent, element.parent.name))
    return refs


def _owned_user_tables(metadata: Any) -> dict[str, list[Any]]:
    owned: dict[str, list[Any]] = {}
    for table in metadata.tables.values():
        refs = _user_foreign_keys(table)
        owner_refs = [column for column, name in refs if name in OWNER_COLUMNS]
        if table.name == "organization_members":
            owner_refs = [column for column, name in refs if name == "user_id"]
        if owner_refs:
            owned[table.name] = owner_refs
    return owned


def _actor_updates(metadata: Any) -> list[tuple[Table, Any]]:
    updates: list[tuple[Table, Any]] = []
    for table in metadata.tables.values():
        for column, name in _user_foreign_keys(table):
            if name in ACTOR_COLUMNS and name not in OWNER_COLUMNS and column.nullable:
                updates.append((table, column))
    return updates


async def _owned_organization_ids(session: AsyncSession, user_ids: Sequence[UUID]) -> list[UUID]:
    if not user_ids:
        return []
    orgs = (
        await session.execute(
            select(Organization.id).where(Organization.created_by_user_id.in_(user_ids))
        )
    ).scalars().all()
    for organization_id in orgs:
        member_count = await session.scalar(
            select(OrganizationMember.id)
            .where(OrganizationMember.organization_id == organization_id)
            .limit(1)
        )
        other_member = await session.scalar(
            select(OrganizationMember.id)
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id.not_in(user_ids),
            )
            .limit(1)
        )
        if other_member is not None:
            raise ResetSafetyError(
                f"Refusing reset: organization {organization_id} has another member"
            )
        if member_count is None:
            raise ResetSafetyError(
                f"Refusing reset: organization {organization_id} has no membership owner"
            )
    return list(orgs)


async def reset_users(
    session: AsyncSession, emails: Sequence[str], *, dry_run: bool = False
) -> ResetResult:
    """Discover or delete selected users and owned rows in one transaction."""

    users = (
        await session.execute(select(User).where(User.email.in_(emails)).with_for_update())
    ).scalars().all()
    if not users:
        return ResetResult(counts={})
    user_ids = [user.id for user in users]
    organization_ids = await _owned_organization_ids(session, user_ids)
    metadata = Base.metadata
    depths = _table_depths(metadata)
    owned_tables = _owned_user_tables(metadata)
    counts: dict[str, int] = {}
    pending_rows = (
        await session.execute(select(PendingSignup).where(PendingSignup.email.in_(emails)))
    ).scalars().all()
    storage_objects = await _collect_storage_objects(
        session, user_ids=user_ids, owned_tables=owned_tables, settings=get_settings()
    )

    if dry_run:
        for _organization_id in organization_ids:
            counts["organizations"] = counts.get("organizations", 0) + 1
        for table, column in _actor_updates(metadata):
            count = await session.scalar(
                select(func.count())
                .select_from(table)
                .where(column.in_(user_ids))
            )
            if count:
                counts[f"{table.name}.{column.name}:detached"] = int(count)
        for table_name, owner_columns in owned_tables.items():
            table = metadata.tables[table_name]
            count = await session.scalar(
                select(func.count())
                .select_from(table)
                .where(or_(*[column.in_(user_ids) for column in owner_columns]))
            )
            if count:
                counts[table_name] = int(count)
        counts["pending_signups"] = len(pending_rows)
        counts["users"] = len(user_ids)
        if storage_objects:
            counts["s3_objects"] = len(storage_objects)
        return ResetResult(
            counts=counts,
            pending_signup_ids=tuple(row.id for row in pending_rows),
            storage_objects=tuple(storage_objects),
        )

    # Delete organizations owned exclusively by the selected users first. Their
    # organization-owned records then follow their declared FK cascades.
    if organization_ids:
        result = await session.execute(
            delete(Organization).where(Organization.id.in_(organization_ids))
        )
        counts["organizations"] = result.rowcount or 0

    # Clear nullable actor references so organization-owned history survives.
    for table, column in _actor_updates(metadata):
        result = await session.execute(
            update(table).where(column.in_(user_ids)).values({column: None})
        )
        if result.rowcount:
            counts[f"{table.name}.{column.name}:detached"] = result.rowcount

    for table_name in sorted(owned_tables, key=lambda name: depths.get(name, 0), reverse=True):
        table = metadata.tables[table_name]
        predicates = [column.in_(user_ids) for column in owned_tables[table_name]]
        result = await session.execute(delete(table).where(or_(*predicates)))
        if result.rowcount:
            counts[table_name] = result.rowcount

    pending = await session.execute(delete(PendingSignup).where(PendingSignup.email.in_(emails)))
    if pending.rowcount:
        counts["pending_signups"] = pending.rowcount

    result = await session.execute(delete(User).where(User.id.in_(user_ids)))
    counts["users"] = result.rowcount or 0
    if counts["users"] != len(user_ids):
        raise ResetSafetyError("Reset did not delete exactly the selected users")
    return ResetResult(
        counts=counts,
        pending_signup_ids=tuple(row.id for row in pending_rows),
        storage_objects=tuple(storage_objects),
    )


async def _collect_storage_objects(
    session: AsyncSession,
    *,
    user_ids: Sequence[UUID],
    owned_tables: dict[str, list[Any]],
    settings: Any,
) -> list[tuple[str, str]]:
    """Collect only object metadata owned by the selected users before deletion."""

    objects: list[tuple[str, str]] = []
    for table_name, owner_columns in owned_tables.items():
        table = Base.metadata.tables[table_name]
        object_columns = [table.c[name] for name in OBJECT_COLUMNS if name in table.c]
        if not object_columns:
            continue
        bucket_column = table.c.get("storage_bucket")
        if bucket_column is None:
            bucket_column = table.c.get("bucket")
        for object_column in object_columns:
            selected_columns = [object_column]
            if bucket_column is not None:
                selected_columns.append(bucket_column)
            rows = await session.execute(
                select(*selected_columns).where(*[column.in_(user_ids) for column in owner_columns])
            )
            for row in rows:
                key = row[0]
                bucket = row[1] if bucket_column is not None else settings.s3_documents_bucket
                if key and bucket:
                    objects.append((str(bucket), str(key)))

    user = await session.execute(
        select(User.avatar_key).where(User.id.in_(user_ids), User.avatar_key.is_not(None))
    )
    for (key,) in user:
        if key and settings.s3_documents_bucket:
            objects.append((settings.s3_documents_bucket, str(key)))
    return list(dict.fromkeys(objects))


async def _delete_storage_objects(objects: Sequence[tuple[str, str]], settings: Any) -> int:
    if not objects:
        return 0
    from app.infrastructure.s3.client import get_s3_client

    client = get_s3_client(settings)
    deleted = 0
    for bucket, key in objects:
        client.delete_object(Bucket=bucket, Key=key)
        deleted += 1
    return deleted


async def run_reset(mode: ResetMode) -> dict[str, int]:
    """Run the database reset and clear matching Redis OTP state."""

    settings = get_settings()
    validate_environment(app_env=settings.app_env, full_reset=mode.full_reset)
    async with async_session_factory() as session:
        async with session.begin():
            if mode.full_reset:
                user_ids = (
                    await session.execute(select(User.id).where(User.role == "user"))
                ).scalars().all()
                emails = (
                    list(
                        (
                            await session.execute(select(User.email).where(User.id.in_(user_ids)))
                        ).scalars().all()
                    )
                    if user_ids
                    else []
                )
            else:
                emails = mode.emails
            result = await reset_users(session, emails, dry_run=mode.dry_run)

    if result.pending_signup_ids and not mode.dry_run:
        from redis.asyncio import Redis

        from app.auth.signup_otp import SIGNUP_OTP_PURPOSE
        from app.infrastructure.redis.keys import RedisKeys

        redis = Redis.from_url(settings.redis_url)
        keys = RedisKeys(settings)
        try:
            for signup_id in result.pending_signup_ids:
                for channel in ("email", "phone"):
                    await redis.delete(
                        keys.otp(
                            purpose=f"{SIGNUP_OTP_PURPOSE}:{channel}",
                            subject=str(signup_id),
                        )
                    )
                    await redis.delete(
                        keys.rate_limit(
                            bucket=f"signup_otp_send:{channel}",
                            identifier=str(signup_id),
                        )
                    )
        finally:
            await redis.aclose()

    if result.storage_objects and not mode.dry_run:
        result.counts["s3_objects"] = await _delete_storage_objects(
            result.storage_objects, settings
        )
    return result.counts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QA-only Kairo test-data reset tool")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--email", help="Reset one exact email address")
    group.add_argument("--emails", metavar="FILE", help="Reset one email per line")
    group.add_argument(
        "--full-reset",
        action="store_true",
        help="Reset all non-system users in staging",
    )
    parser.add_argument(
        "--confirm-full-reset",
        action="store_true",
        help="Explicitly confirm the destructive full staging reset",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the single-user confirmation prompt",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover affected records without changing the database, Redis, or S3",
    )
    return parser


async def async_main(argv: Sequence[str]) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    validate_environment(app_env=settings.app_env, full_reset=args.full_reset)
    mode = parse_mode(email=args.email, emails_file=args.emails, full_reset=args.full_reset)
    mode = ResetMode(emails=mode.emails, full_reset=mode.full_reset, dry_run=args.dry_run)
    if mode.full_reset and not mode.dry_run:
        confirm_full_reset(confirmed=args.confirm_full_reset)
    elif not mode.full_reset and not mode.dry_run and not args.yes:
        answer = input("Type RESET to delete the selected QA users: ")
        if answer != "RESET":
            raise ResetSafetyError("Reset cancelled")
    counts = await run_reset(mode)
    if mode.dry_run:
        print("DRY RUN: no destructive action occurred")
    for table, count in sorted(counts.items()):
        print(f"{table}: {count}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return asyncio.run(async_main(argv or sys.argv[1:]))
    except (ResetSafetyError, ValueError) as exc:
        print(f"reset refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
