from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update

from app.config import get_settings
from app.db.session import async_session_factory
from app.models import (
    AccountDeletion,
    AccountDeletionItem,
    Organization,
    OrganizationDeletionResolution,
    OrganizationMember,
    User,
)
from app.ops.clean_slate import ProgressStore, load_allowlist
from app.organization.enums import OrganizationRole, OrganizationType
from app.services.account_deletion_service import AccountDeletionService
from app.services.clean_slate_orchestrator import (
    CleanSlateAllowlist,
    CleanSlateOrchestrator,
    CleanSlateSafetyError,
    storage_identity,
    verify_artifact_checksum,
)


class FakeRedis:
    async def delete(self, *keys):  # noqa: ANN002, ANN201
        return len(keys)


def allowlist_payload(**overrides) -> bytes:  # noqa: ANN003
    value = {
        "schema_version": 1,
        "environment": "test",
        "approved_user_ids": [],
        "approved_pending_signup_ids": [],
        "approved_organization_ids": [],
        "approved_storage_object_ids": [],
        "protected_user_ids": [],
        "backup_evidence": None,
    }
    value.update(overrides)
    return json.dumps(value, sort_keys=True).encode()


def test_allowlist_parser_requires_exact_schema() -> None:
    payload = json.loads(allowlist_payload())
    payload["unexpected"] = True
    with pytest.raises(CleanSlateSafetyError, match="invalid_allowlist_schema"):
        load_allowlist(json.dumps(payload).encode())


def test_allowlist_parser_rejects_duplicate_ids() -> None:
    target = str(uuid4())
    with pytest.raises(CleanSlateSafetyError, match="duplicate_approved_user_ids"):
        load_allowlist(allowlist_payload(approved_user_ids=[target, target]))


def test_allowlist_checksum_rejects_tampering() -> None:
    payload = allowlist_payload()
    expected = hashlib.sha256(payload).hexdigest()
    verify_artifact_checksum(payload, expected)
    with pytest.raises(CleanSlateSafetyError, match="allowlist_checksum_mismatch"):
        verify_artifact_checksum(payload + b"\n", expected)


def test_progress_store_writes_atomic_checkpoint(tmp_path) -> None:  # noqa: ANN001
    path = tmp_path / "progress.json"
    store = ProgressStore(
        artifact_sha256="a" * 64,
        local_path=path,
        s3_uri=None,
        settings=None,
    )
    store.record({"event": "clean_slate_user_committed", "user_id": str(uuid4())})
    value = json.loads(path.read_text())
    assert value["allowlist_sha256"] == "a" * 64
    assert len(value["events"]) == 1
    assert not path.with_suffix(".json.tmp").exists()
    restored = ProgressStore(
        artifact_sha256="a" * 64,
        local_path=path,
        s3_uri=None,
        settings=None,
    )
    assert len(restored.completed_user_ids) == 1


def test_progress_store_rejects_other_allowlist(tmp_path) -> None:  # noqa: ANN001
    path = tmp_path / "progress.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "allowlist_sha256": "b" * 64,
                "events": [],
            }
        )
    )
    with pytest.raises(CleanSlateSafetyError, match="progress_artifact_mismatch"):
        ProgressStore(
            artifact_sha256="a" * 64,
            local_path=path,
            s3_uri=None,
            settings=None,
        )


async def _user(session, *, role: str = "user") -> User:  # noqa: ANN001
    user = User(
        id=uuid4(),
        email=f"clean-slate-{uuid4()}@example.test",
        role=role,
        is_active=True,
        email_verified_at=datetime.now(UTC),
    )
    session.add(user)
    await session.flush()
    return user


def _allowlist(
    target: UUID,
    *,
    organizations: frozenset[UUID] = frozenset(),
    storage: frozenset[str] = frozenset(),
    protected: frozenset[UUID] = frozenset(),
) -> CleanSlateAllowlist:
    return CleanSlateAllowlist(
        schema_version=1,
        environment="test",
        approved_user_ids=frozenset({target}),
        approved_pending_signup_ids=frozenset(),
        approved_organization_ids=organizations,
        approved_storage_object_ids=storage,
        protected_user_ids=protected,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_dry_run_is_zero_mutation_and_preserves_unlisted_user() -> None:
    settings = get_settings().model_copy(
        update={
            "s3_documents_bucket": "clean-slate-test",
            "s3_document_key_prefix": "test",
            "sqs_main_queue_url": None,
        }
    )
    ids: list[UUID] = []
    try:
        async with async_session_factory() as session:
            target = await _user(session)
            survivor = await _user(session)
            target_id = target.id
            survivor_id = survivor.id
            ids.extend((target_id, survivor_id))
            await session.commit()
            orchestrator = CleanSlateOrchestrator(
                session,
                settings,
                FakeRedis(),
                object_lister=lambda _bucket, _scopes: _empty_keys(),
            )
            plan = await orchestrator.plan(_allowlist(target_id))
            assert plan.users == (str(target_id),)
            assert plan.storage_object_count == 0
            await session.rollback()
        async with async_session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(User).where(User.id.in_((target_id, survivor_id)))
                    )
                ).all()
            )
            assert len(rows) == 2
            assert all(row.deleted_at is None and row.is_active for row in rows)
            assert await session.scalar(
                select(AccountDeletion.id).where(AccountDeletion.user_id == target_id)
            ) is None
    finally:
        await _cleanup(ids)


async def _empty_keys() -> set[str]:
    return set()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_protected_identity_is_blocked_before_mutation() -> None:
    settings = get_settings().model_copy(
        update={"s3_documents_bucket": "clean-slate-test", "s3_document_key_prefix": "test"}
    )
    ids: list[UUID] = []
    try:
        async with async_session_factory() as session:
            admin = await _user(session, role="admin")
            ids.append(admin.id)
            await session.commit()
            orchestrator = CleanSlateOrchestrator(
                session,
                settings,
                FakeRedis(),
                object_lister=lambda _bucket, _scopes: _empty_keys(),
            )
            with pytest.raises(CleanSlateSafetyError, match="protected_identity_targeted"):
                await orchestrator.plan(_allowlist(admin.id, protected=frozenset({admin.id})))
        async with async_session_factory() as session:
            row = await session.get(User, admin.id)
            assert row is not None and row.deleted_at is None
    finally:
        await _cleanup(ids)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_unapproved_organization_dependency_is_blocked() -> None:
    settings = get_settings().model_copy(
        update={"s3_documents_bucket": "clean-slate-test", "s3_document_key_prefix": "test"}
    )
    ids: list[UUID] = []
    org_ids: list[UUID] = []
    try:
        async with async_session_factory() as session:
            owner = await _user(session)
            ids.append(owner.id)
            organization = Organization(
                id=uuid4(),
                created_by_user_id=owner.id,
                name="Synthetic protected organization",
                organization_type=OrganizationType.EMPLOYER,
            )
            session.add(organization)
            await session.flush()
            org_ids.append(organization.id)
            session.add(
                OrganizationMember(
                    organization_id=organization.id,
                    user_id=owner.id,
                    role=OrganizationRole.OWNER,
                )
            )
            await session.commit()
            orchestrator = CleanSlateOrchestrator(
                session,
                settings,
                FakeRedis(),
                object_lister=lambda _bucket, _scopes: _empty_keys(),
            )
            with pytest.raises(CleanSlateSafetyError, match="organization_not_allowlisted"):
                await orchestrator.plan(_allowlist(owner.id))
            plan = await orchestrator.plan(
                _allowlist(owner.id, organizations=frozenset({organization.id}))
            )
            assert plan.organizations == (str(organization.id),)
    finally:
        await _cleanup(ids, org_ids)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_storage_reconciliation_requires_exact_hashes_for_execution() -> None:
    settings = get_settings().model_copy(
        update={"s3_documents_bucket": "clean-slate-test", "s3_document_key_prefix": "test"}
    )
    ids: list[UUID] = []
    try:
        async with async_session_factory() as session:
            target = await _user(session)
            ids.append(target.id)
            await session.commit()
            key = f"resumes/{target.id}/fixture.pdf"

            async def keys(_bucket, _scopes):  # noqa: ANN001, ANN202
                return {key}

            orchestrator = CleanSlateOrchestrator(
                session, settings, FakeRedis(), object_lister=keys
            )
            plan = await orchestrator.plan(_allowlist(target.id))
            expected = storage_identity("clean-slate-test", key)
            assert plan.storage_object_ids == (expected,)
            with pytest.raises(CleanSlateSafetyError, match="storage_allowlist_mismatch"):
                await orchestrator.plan(
                    _allowlist(target.id), require_storage_allowlist=True
                )
            strict = await orchestrator.plan(
                _allowlist(target.id, storage=frozenset({expected})),
                require_storage_allowlist=True,
            )
            assert strict.storage_object_count == 1
    finally:
        await _cleanup(ids)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_unknown_storage_ownership_fails_closed() -> None:
    settings = get_settings().model_copy(
        update={"s3_documents_bucket": "clean-slate-test", "s3_document_key_prefix": "test"}
    )
    ids: list[UUID] = []
    try:
        async with async_session_factory() as session:
            target = await _user(session)
            ids.append(target.id)
            await session.commit()

            async def unsafe_keys(_bucket, _scopes):  # noqa: ANN001, ANN202
                return {"application-static/brand/logo.png"}

            orchestrator = CleanSlateOrchestrator(
                session,
                settings,
                FakeRedis(),
                object_lister=unsafe_keys,
            )
            with pytest.raises(CleanSlateSafetyError, match="unknown_storage_ownership"):
                await orchestrator.plan(_allowlist(target.id))
    finally:
        await _cleanup(ids)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_operator_deletion_is_canonical_and_idempotent() -> None:
    settings = get_settings().model_copy(
        update={
            "s3_documents_bucket": "clean-slate-test",
            "s3_document_key_prefix": "test",
            "sqs_main_queue_url": None,
        }
    )
    ids: list[UUID] = []
    try:
        async with async_session_factory() as session:
            target = await _user(session)
            ids.append(target.id)
            await session.commit()
            service = AccountDeletionService(session, settings, FakeRedis())
            first = await service.delete_candidate_account_by_operator(target.id)
            second = await service.delete_candidate_account_by_operator(target.id)
            assert first == second
        async with async_session_factory() as session:
            user = await session.get(User, target.id)
            assert user is not None and user.deleted_at is not None and not user.is_active
            ledgers = list(
                (
                    await session.scalars(
                        select(AccountDeletion).where(AccountDeletion.user_id == target.id)
                    )
                ).all()
            )
            assert len(ledgers) == 1
            assert len(
                (
                    await session.scalars(
                        select(AccountDeletionItem).where(
                            AccountDeletionItem.deletion_id == ledgers[0].id
                        )
                    )
                ).all()
            ) >= 7
    finally:
        await _cleanup(ids)


async def _cleanup(user_ids: list[UUID], organization_ids: list[UUID] | None = None) -> None:
    organization_ids = organization_ids or []
    async with async_session_factory() as session:
        deletion_ids = select(AccountDeletion.id).where(AccountDeletion.user_id.in_(user_ids))
        await session.execute(
            delete(AccountDeletionItem).where(AccountDeletionItem.deletion_id.in_(deletion_ids))
        )
        await session.execute(
            delete(OrganizationDeletionResolution).where(
                OrganizationDeletionResolution.organization_id.in_(organization_ids)
            )
        )
        await session.execute(
            update(User).where(User.id.in_(user_ids)).values(active_organization_id=None)
        )
        await session.execute(delete(Organization).where(Organization.id.in_(organization_ids)))
        await session.execute(delete(AccountDeletion).where(AccountDeletion.user_id.in_(user_ids)))
        await session.execute(delete(User).where(User.id.in_(user_ids)))
        await session.commit()
