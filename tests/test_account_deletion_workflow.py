"""Real local transactions, synthetic identities and fake object storage only."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import delete, func, select, update
from starlette.requests import Request

from app.auth.deps import get_current_user
from app.auth.service import AuthService
from app.auth.tokens import create_access_token
from app.config import get_settings
from app.db.session import async_session_factory
from app.exceptions import NotFoundError, ServiceUnavailableError, UnauthorizedError
from app.models import (
    AccountDeletion,
    AccountDeletionItem,
    DocumentSharePack,
    DocumentSharePackItem,
    Education,
    EducationDocument,
    RefreshToken,
    User,
    UserDocument,
    VerificationRequest,
    VerificationRequestEvent,
    VerificationRequestEvidence,
)
from app.schemas.account_deletion import AccountDeletionRequest
from app.schemas.auth import RefreshRequest
from app.services.account_deletion_inventory import identity, safe_key
from app.services.account_deletion_purge import PurgeStorage, sweep_deletions
from app.services.account_deletion_service import AccountDeletionService
from app.services.document_share_pack_service import DocumentSharePackService
from app.services.private_owner_guard import lock_private_owner


class FakeRedis:
    def __init__(self):
        self.deleted = []

    async def delete(self, key):
        self.deleted.append(key)


class FakeStorage:
    def __init__(self):
        self.objects = set()
        self.deleted = []
        self.fail = set()
        self.crash = False

    async def discover(self, bucket, prefix):
        return sorted(key for key in self.objects if key.startswith(prefix)), False

    async def purge(self, bucket, key):
        if key in self.fail:
            raise ConnectionError("must never be logged: sensitive-storage-reference")
        self.deleted.append(key)
        self.objects.discard(key)
        if self.crash:
            raise asyncio.CancelledError()


@pytest.fixture
async def case():
    settings = get_settings().model_copy(
        update={
            "s3_documents_bucket": "synthetic-account-deletion",
            "s3_document_key_prefix": "test",
            "sqs_main_queue_url": None,
        }
    )
    uid, other = uuid4(), uuid4()
    redis, storage = FakeRedis(), FakeStorage()
    key = f"test/user-documents/{uid}/{uuid4()}/synthetic.pdf"
    other_key = f"test/user-documents/{other}/{uuid4()}/synthetic.pdf"
    async with async_session_factory() as session:
        session.add_all(
            [
                User(
                    id=person,
                    email=f"{person}@example.test",
                    role="user",
                    is_active=True,
                    email_verified_at=datetime.now(UTC),
                    suspension_reason="Synthetic private reason",
                )
                for person in (uid, other)
            ]
        )
        await session.flush()
        session.add_all(
            [
                UserDocument(
                    user_id=person,
                    object_key=object_key,
                    document_type="passport",
                    original_filename="synthetic.pdf",
                    content_type="application/pdf",
                    byte_size=10,
                    checksum_sha256="a" * 64,
                )
                for person, object_key in ((uid, key), (other, other_key))
            ]
        )
        await session.commit()
    storage.objects.update({key, other_key})
    result = SimpleNamespace(
        uid=uid,
        other=other,
        key=key,
        other_key=other_key,
        settings=settings,
        redis=redis,
        storage=storage,
    )
    yield result
    async with async_session_factory() as cleanup:
        ids = select(AccountDeletion.id).where(AccountDeletion.user_id.in_([uid, other]))
        await cleanup.execute(
            delete(AccountDeletionItem).where(AccountDeletionItem.deletion_id.in_(ids))
        )
        await cleanup.execute(
            delete(AccountDeletion).where(AccountDeletion.user_id.in_([uid, other]))
        )
        await cleanup.execute(delete(User).where(User.id.in_([uid, other])))
        await cleanup.commit()


async def erase(case):
    async with async_session_factory() as session:
        await AccountDeletionService(session, case.settings, case.redis).delete_candidate_account(
            case.uid, AccountDeletionRequest(confirm="DELETE")
        )
        return await session.scalar(
            select(AccountDeletion.id).where(AccountDeletion.user_id == case.uid)
        )


async def sweep(case, deletion_id, *, advance=2):
    async with async_session_factory() as session:
        return await sweep_deletions(
            session,
            case.settings,
            case.redis,
            storage=case.storage,
            deletion_id=deletion_id,
            now=datetime.now(UTC) + timedelta(hours=advance),
        )


async def item_for(case, key):
    async with async_session_factory() as session:
        return await session.scalar(
            select(AccountDeletionItem)
            .join(AccountDeletion)
            .where(
                AccountDeletion.user_id == case.uid,
                AccountDeletionItem.identity_hash == identity("object", key),
            )
        )


async def test_transaction_commits_ledger_before_any_storage_and_deduplicates(case):
    deletion_id = await erase(case)
    assert case.storage.deleted == []
    assert (await item_for(case, case.key)).status == "pending"
    assert await item_for(case, case.other_key) is None
    assert await erase(case) == deletion_id
    async with async_session_factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AccountDeletion)
                .where(AccountDeletion.user_id == case.uid)
            )
            == 1
        )
        user = await session.get(User, case.uid)
        assert user.deleted_at and not user.is_active
        assert user.suspension_reason is None
    assert (await sweep(case, deletion_id))["status"] == "complete"
    assert case.key not in case.storage.objects
    assert case.other_key in case.storage.objects
    assert (await item_for(case, case.key)).object_key is None


async def test_db_commit_failure_rolls_back_everything_without_storage(case, monkeypatch):
    async with async_session_factory() as session:

        async def fail_commit():
            raise RuntimeError("synthetic database failure")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(ServiceUnavailableError, match="could not be completed"):
            await AccountDeletionService(
                session, case.settings, case.redis
            ).delete_candidate_account(case.uid, AccountDeletionRequest(confirm="DELETE"))
    async with async_session_factory() as session:
        assert (await session.get(User, case.uid)).deleted_at is None
        assert (
            await session.scalar(
                select(AccountDeletion.id).where(AccountDeletion.user_id == case.uid)
            )
            is None
        )
        assert (
            await session.scalar(select(UserDocument.id).where(UserDocument.user_id == case.uid))
            is not None
        )
    assert case.storage.deleted == []


async def test_queue_publish_failure_recovers_from_database(case, monkeypatch):
    case.settings.sqs_main_queue_url = "https://queue.example.test/synthetic"

    async def unavailable(envelope, **kwargs):
        assert set(envelope.data) == {"deletion_id"}
        raise ConnectionError("synthetic queue outage")

    monkeypatch.setattr("app.services.account_deletion_service.send_json_message", unavailable)
    deletion_id = await erase(case)
    async with async_session_factory() as session:
        # Make only this test request the oldest due item; the sweeper receives no
        # queue payload or request ID and must discover it from durable state.
        await session.execute(
            update(AccountDeletion)
            .where(AccountDeletion.id == deletion_id)
            .values(next_attempt_at=datetime(2000, 1, 1, tzinfo=UTC))
        )
        await session.execute(
            update(AccountDeletionItem)
            .where(AccountDeletionItem.deletion_id == deletion_id)
            .values(next_attempt_at=datetime(2000, 1, 1, tzinfo=UTC))
        )
        await session.commit()
    async with async_session_factory() as session:
        result = await sweep_deletions(session, case.settings, case.redis, storage=case.storage)
        assert result["status"] == "complete"
    assert case.key not in case.storage.objects


async def test_duplicate_queue_handler_delivery_is_idempotent(case, monkeypatch):
    from app.workers.handlers import account_deletion as handler

    deletion_id = await erase(case)
    async with async_session_factory() as session:
        await session.execute(
            update(AccountDeletion)
            .where(AccountDeletion.id == deletion_id)
            .values(next_attempt_at=datetime(2000, 1, 1, tzinfo=UTC))
        )
        await session.execute(
            update(AccountDeletionItem)
            .where(AccountDeletionItem.deletion_id == deletion_id)
            .values(next_attempt_at=datetime(2000, 1, 1, tzinfo=UTC))
        )
        await session.commit()

    class RedisContext:
        async def __aenter__(self):
            return case.redis

        async def __aexit__(self, *_):
            return False

    monkeypatch.setattr(handler, "get_settings", lambda: case.settings)
    monkeypatch.setattr(handler.Redis, "from_url", lambda _: RedisContext())
    monkeypatch.setattr("app.services.account_deletion_purge.PurgeStorage", lambda _: case.storage)
    await handler.purge_account({"deletion_id": str(deletion_id)}, None)
    initial = list(case.storage.deleted)
    await handler.purge_account({"deletion_id": str(deletion_id)}, None)
    assert initial == case.storage.deleted
    assert case.key not in case.storage.objects


async def test_storage_outage_is_partial_sanitized_and_retryable(case, caplog):
    case.storage.fail.add(case.key)
    deletion_id = await erase(case)
    result = await sweep(case, deletion_id)
    assert result["status"] == "purge_partial"
    assert result["last_error_category"] == "cleanup_temporarily_unavailable"
    async with async_session_factory() as session:
        assert not (await session.get(User, case.uid)).is_active
    assert "sensitive-storage-reference" not in caplog.text
    assert case.key not in caplog.text
    case.storage.fail.clear()
    assert (await sweep(case, deletion_id, advance=4))["status"] == "complete"


async def test_crash_after_physical_delete_recovers_without_queue(case):
    deletion_id = await erase(case)
    case.storage.crash = True
    with pytest.raises(asyncio.CancelledError):
        await sweep(case, deletion_id)
    assert (await item_for(case, case.key)).status == "pending"
    case.storage.crash = False
    assert (await sweep(case, deletion_id, advance=4))["status"] == "complete"


async def test_missing_objects_and_duplicate_sweep_are_success(case):
    case.storage.objects.discard(case.key)
    deletion_id = await erase(case)
    assert (await sweep(case, deletion_id))["status"] == "complete"
    initial = list(case.storage.deleted)
    assert (await sweep(case, deletion_id, advance=4))["status"] == "complete"
    assert initial == case.storage.deleted


async def test_orphan_and_late_put_discovered_durably_before_delete(case):
    orphan = f"test/certifications/{case.uid}/{uuid4()}/{uuid4()}/orphan.pdf"
    case.storage.objects.add(orphan)
    deletion_id = await erase(case)
    assert (await sweep(case, deletion_id))["status"] == "purge_pending"
    assert orphan in case.storage.objects
    assert (await item_for(case, orphan)).status == "pending"
    assert (await sweep(case, deletion_id, advance=4))["status"] == "complete"
    case.storage.objects.add(orphan)  # Previously issued PUT finishes late.
    assert (await sweep(case, deletion_id, advance=6))["status"] == "purge_pending"
    assert (await sweep(case, deletion_id, advance=8))["status"] == "complete"


@pytest.mark.parametrize(
    "bad",
    [
        "https://bucket.example/private",
        "../private",
        "/private",
        "test/../private",
        "test//private",
        "test/private?sig=secret",
    ],
)
async def test_malformed_legacy_reference_is_review_never_deleted(case, bad):
    async with async_session_factory() as session:
        doc = await session.scalar(select(UserDocument).where(UserDocument.user_id == case.uid))
        doc.object_key = bad
        await session.commit()
    deletion_id = await erase(case)
    assert (await sweep(case, deletion_id))["review"] == 1
    assert (await sweep(case, deletion_id, advance=4))["status"] == "operator_review"
    assert bad not in case.storage.deleted


async def test_cross_user_reference_in_corrupted_metadata_fails_closed(case):
    async with async_session_factory() as session:
        doc = await session.scalar(select(UserDocument).where(UserDocument.user_id == case.uid))
        # A distinct key under the other user's prefix, avoiding the unique-key constraint.
        doc.object_key = f"test/user-documents/{case.other}/foreign.pdf"
        foreign = doc.object_key
        await session.commit()
    case.storage.objects.add(foreign)
    deletion_id = await erase(case)
    assert (await sweep(case, deletion_id))["review"] == 1
    assert (await sweep(case, deletion_id, advance=4))["status"] == "operator_review"
    assert foreign in case.storage.objects
    assert case.other_key in case.storage.objects


@pytest.mark.parametrize("pack_state", ["active", "revoked", "expired"])
async def test_pack_capabilities_removed_and_snapshot_purge_durable(case, pack_state):
    now, pack_id, token = datetime.now(UTC), uuid4(), "synthetic-test-pack-token-" + uuid4().hex
    key = f"test/document-share-packs/{pack_id}/{uuid4()}"
    async with async_session_factory() as session:
        pack = DocumentSharePack(
            id=pack_id,
            owner_user_id=case.uid,
            purpose="Synthetic test",
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            created_at=now - timedelta(days=2),
            expires_at=now + timedelta(days=-1 if pack_state == "expired" else 1),
            revoked_at=now if pack_state == "revoked" else None,
        )
        session.add(pack)
        await session.flush()
        session.add(
            DocumentSharePackItem(
                pack_id=pack_id,
                source_type="vault",
                source_id=uuid4(),
                category="identity",
                title="Synthetic",
                filename="synthetic.pdf",
                content_type="application/pdf",
                byte_size=10,
                object_key=key,
                object_etag="fake",
                owns_snapshot=True,
            )
        )
        await session.commit()
    case.storage.objects.add(key)
    deletion_id = await erase(case)
    async with async_session_factory() as session:
        with pytest.raises(NotFoundError):
            await DocumentSharePackService(session, case.settings).resolve(token)
        assert await session.get(DocumentSharePack, pack_id) is None
    assert (await item_for(case, key)).status == "pending"
    case.storage.fail.add(key)
    assert (await sweep(case, deletion_id))["status"] == "purge_partial"
    case.storage.fail.clear()
    case.storage.objects.discard(key)
    assert (await sweep(case, deletion_id, advance=4))["status"] == "complete"


async def test_real_session_and_refresh_cannot_resurrect_deleted_owner(case):
    raw, family = "synthetic-refresh-" + uuid4().hex, uuid4()
    async with async_session_factory() as session:
        session.add(
            RefreshToken(
                user_id=case.uid,
                family_id=family,
                token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        await session.commit()
        token = create_access_token(
            case.settings, subject=case.uid, role="user", extra_claims={"sid": str(family)}
        )
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        assert (
            await get_current_user(credentials=credentials, session=session, settings=case.settings)
        ).id == case.uid
    await erase(case)
    async with async_session_factory() as session:
        with pytest.raises(UnauthorizedError):
            await get_current_user(credentials=credentials, session=session, settings=case.settings)
        with pytest.raises(UnauthorizedError):
            await AuthService(session, case.settings, case.redis).refresh(
                RefreshRequest(refresh_token=raw)
            )


async def test_candidate_write_dependency_rechecks_after_deletion(case):
    await erase(case)
    async with async_session_factory() as session:
        with pytest.raises(NotFoundError):
            await lock_private_owner(session, case.uid)


async def test_concurrent_delete_serializes_to_one_ledger(case):
    results = await asyncio.gather(erase(case), erase(case))
    assert results[0] == results[1]


async def test_worker_rejects_uncommitted_caller_session(case):
    async with async_session_factory() as session:
        await session.get(User, case.uid)
        with pytest.raises(RuntimeError, match="fresh post-commit"):
            await sweep_deletions(session, case.settings, case.redis, storage=case.storage)
    assert case.storage.deleted == []


async def test_worker_bucket_mismatch_never_deletes(case):
    deletion_id = await erase(case)
    case.settings.s3_documents_bucket = "other-environment"
    assert (await sweep(case, deletion_id))["status"] == "operator_review"
    assert case.storage.deleted == []


async def test_storage_permission_failure_requires_review_not_false_completion(case, monkeypatch):
    async def forbidden(bucket, key):
        raise ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "private-ref"}}, "DeleteObject"
        )

    monkeypatch.setattr(case.storage, "purge", forbidden)
    deletion_id = await erase(case)
    result = await sweep(case, deletion_id)
    assert result["status"] == "operator_review"
    item = await item_for(case, case.key)
    assert item.last_error_category == "storage_permission_or_configuration"
    repeated = await sweep(case, deletion_id, advance=4)
    assert repeated["status"] == "operator_review"
    assert repeated["last_error_category"] == "storage_permission_or_configuration"
    assert (await item_for(case, case.key)).attempts == item.attempts


async def test_worker_refuses_inconsistent_active_owner_and_pack_cannot_resurrect(case):
    deletion_id = await erase(case)
    async with async_session_factory() as session:
        with pytest.raises(NotFoundError):
            await DocumentSharePackService(session, case.settings).create(case.uid, None)
        owner = await session.get(User, case.uid)
        owner.is_active = True  # Synthetic corruption only, not an authorized restoration path.
        await session.commit()
    assert (await sweep(case, deletion_id))["status"] == "operator_review"
    assert case.storage.deleted == []


@pytest.mark.parametrize("binding", ["exact", "ambiguous"])
async def test_education_evidence_erased_without_inventing_historical_binding(case, binding):
    eid, rid, other_rid = uuid4(), uuid4(), uuid4()
    key = f"test/education-documents/{eid}/{uuid4()}/synthetic.pdf"
    try:
        async with async_session_factory() as session:
            session.add(
                Education(
                    id=eid,
                    user_id=case.uid,
                    institution_name="Synthetic School",
                    reviewer_note="private note",
                )
            )
            await session.flush()
            doc = EducationDocument(
                education_id=eid,
                uploaded_by_user_id=case.uid,
                document_type="degree_certificate",
                object_key=key,
                original_filename="synthetic.pdf",
                content_type="application/pdf",
                byte_size=10,
                checksum_sha256="b" * 64,
            )
            session.add(doc)
            await session.flush()
            session.add_all(
                [
                    VerificationRequest(
                        id=rid,
                        origin_type="subject_initiated",
                        subject_user_id=case.uid,
                        education_id=eid,
                        subject_name="Synthetic Candidate",
                        subject_email=f"{case.uid}@example.test",
                        request_type="education",
                        status="verified",
                        requested_by_user_id=case.uid,
                        claim_snapshot={"private": "erase"},
                        candidate_response="private note",
                    ),
                    # Being the requester is not ownership of the subject's records.
                    VerificationRequest(
                        id=other_rid,
                        origin_type="subject_initiated",
                        subject_user_id=case.other,
                        subject_name="Other Candidate",
                        subject_email=f"{case.other}@example.test",
                        request_type="education",
                        status="verified",
                        requested_by_user_id=case.uid,
                        claim_snapshot={"other": "preserve"},
                    ),
                ]
            )
            await session.flush()
            evidence = VerificationRequestEvidence(
                verification_request_id=rid,
                submitted_by_user_id=case.uid,
                evidence_type="document",
                field_key="degree_certificate",
                status="submitted",
                education_document_id=doc.id if binding == "exact" else None,
                value={"private": "erase"},
            )
            session.add(evidence)
            event = VerificationRequestEvent(
                verification_request_id=rid,
                event_type="verified",
                event_source="system",
                new_status="verified",
                metadata_payload={"private": "erase"},
            )
            session.add(event)
            await session.commit()
            evidence_id, event_id = evidence.id, event.id
        case.storage.objects.add(key)
        deletion_id = await erase(case)
        async with async_session_factory() as session:
            retained = await session.get(VerificationRequest, rid)
            assert retained.status == "verified"
            assert retained.subject_user_id is None and retained.subject_name == "Deleted Candidate"
            assert retained.claim_snapshot == {} and retained.candidate_response is None
            evidence = await session.get(VerificationRequestEvidence, evidence_id)
            assert evidence.value is None and evidence.education_document_id is None
            assert (await session.get(VerificationRequestEvent, event_id)).metadata_payload == {}
            assert (await session.get(VerificationRequest, other_rid)).claim_snapshot == {
                "other": "preserve"
            }
            assert (await session.get(Education, eid)).deleted_at is not None
            assert (await session.get(Education, eid)).reviewer_note is None
            unresolved = (
                await session.scalars(
                    select(AccountDeletionItem).where(
                        AccountDeletionItem.deletion_id == deletion_id,
                        AccountDeletionItem.kind == "unresolved",
                    )
                )
            ).all()
            assert len(unresolved) == (binding == "ambiguous")
        assert (await item_for(case, key)).status == "pending"
        result = await sweep(case, deletion_id)
        assert result["status"] == ("complete" if binding == "exact" else "operator_review")
        assert key not in case.storage.objects
    finally:
        async with async_session_factory() as session:
            await session.execute(
                delete(VerificationRequest).where(VerificationRequest.id.in_([rid, other_rid]))
            )
            await session.execute(delete(Education).where(Education.id == eid))
            await session.commit()


async def test_pending_put_window_and_foreign_worker_request_are_noops(case):
    deletion_id = await erase(case)
    async with async_session_factory() as session:
        assert (
            await sweep_deletions(
                session, case.settings, case.redis, storage=case.storage, deletion_id=deletion_id
            )
            is None
        )
        assert (
            await sweep_deletions(
                session,
                case.settings,
                case.redis,
                storage=case.storage,
                deletion_id=uuid4(),
                now=datetime.now(UTC) + timedelta(days=1),
            )
            is None
        )
    assert case.storage.deleted == []


async def test_concurrent_sweep_claim_is_skip_locked(case):
    deletion_id = await erase(case)
    async with async_session_factory() as claimed:
        await claimed.scalar(
            select(AccountDeletion).where(AccountDeletion.id == deletion_id).with_for_update()
        )
        assert await sweep(case, deletion_id) is None
    assert (await sweep(case, deletion_id))["status"] == "complete"


async def test_writes_wait_for_owner_guard_before_deletion(case):
    async with async_session_factory() as writing:
        await lock_private_owner(writing, case.uid)
        deleting = asyncio.create_task(erase(case))
        try:
            await asyncio.sleep(0.05)
            assert not deleting.done()
            await writing.commit()
            await deleting
        finally:
            if not deleting.done():
                deleting.cancel()
    async with async_session_factory() as session:
        with pytest.raises(NotFoundError):
            await lock_private_owner(session, case.uid)


async def test_authenticated_write_dependency_holds_owner_guard(case):
    family, raw = uuid4(), "synthetic-" + uuid4().hex
    async with async_session_factory() as auth_session:
        auth_session.add(
            RefreshToken(
                user_id=case.uid,
                family_id=family,
                token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        await auth_session.commit()
        token = create_access_token(
            case.settings, subject=case.uid, role="user", extra_claims={"sid": str(family)}
        )
        await get_current_user(
            request=Request({"type": "http", "method": "POST", "path": "/api/v1/user-documents"}),
            credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
            session=auth_session,
            settings=case.settings,
        )
        deleting = asyncio.create_task(erase(case))
        try:
            await asyncio.sleep(0.05)
            assert not deleting.done()
            await auth_session.commit()
            await deleting
        finally:
            if not deleting.done():
                deleting.cancel()


def test_safe_key_rejects_traversal_and_urls():
    assert safe_key("test/users/synthetic/document.pdf")
    assert not safe_key("test/../organization/private")


async def test_versioned_purge_removes_versions_and_markers_but_not_prefix_sibling():
    class S3:
        rows = [
            {"Key": "owned", "VersionId": "v1"},
            {"Key": "owned", "VersionId": "v2"},
            {"Key": "owned-other", "VersionId": "v3"},
        ]
        markers = [{"Key": "owned", "VersionId": "marker"}]

        def list_object_versions(self, **kwargs):
            return {"Versions": list(self.rows), "DeleteMarkers": list(self.markers)}

        def delete_object(self, Key, VersionId, **kwargs):
            self.rows = [
                row for row in self.rows if (row["Key"], row["VersionId"]) != (Key, VersionId)
            ]
            self.markers = [row for row in self.markers if row["VersionId"] != VersionId]

    storage = PurgeStorage.__new__(PurgeStorage)
    storage.client = S3()
    await storage.purge("synthetic", "owned")
    assert storage.client.rows == [{"Key": "owned-other", "VersionId": "v3"}]
    assert storage.client.markers == []
