"""Synthetic-file tests exercise real PostgreSQL ownership, snapshots and public routes."""

import hashlib
import io
import os
from pathlib import Path
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.v1.routes.document_share_packs import service as service_dependency
from app.config import Settings
from app.exceptions import NotFoundError, ValidationAppError
from app.logging.request_redaction import redact_request_credentials
from app.main import app
from app.models import DocumentSharePack, User, UserDocument, Employment, VerificationRequest
from app.schemas.document_share_pack import DocumentPackCreate
from app.schemas.user_document import UserDocumentUploadIntentRequest
from app.services.document_pack_cleanup import cleanup_document_pack_snapshots
from app.services.document_pack_storage import DocumentPackStorage
from app.services.document_share_pack_service import DocumentSharePackService


class MemoryS3:
    def __init__(self):
        self.objects = {}
        self.deleted = []

    def put(self, key, data=b"%PDF-synthetic harmless QA", version=None):
        self.objects[(key, version)] = data
        return self.head_object(Key=key, VersionId=version)

    def head_object(self, *, Key, VersionId=None, **kwargs):
        data = self.objects.get((Key, VersionId))
        if data is None:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {
            "ETag": hashlib.md5(data).hexdigest(),
            "ContentLength": len(data),
            "ContentType": "application/pdf",
            "VersionId": VersionId,
        }

    def copy_object(self, *, Key, CopySource, CopySourceIfMatch, **kwargs):
        meta = self.head_object(Key=CopySource["Key"])
        if meta["ETag"] != CopySourceIfMatch:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "CopyObject")
        data = self.objects[(CopySource["Key"], None)]
        self.put(Key, data)
        return {"CopyObjectResult": {"ETag": meta["ETag"]}}

    def get_object(self, *, Key, VersionId=None, IfMatch=None, **kwargs):
        meta = self.head_object(Key=Key, VersionId=VersionId)
        if IfMatch != meta["ETag"]:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "GetObject")
        return {**meta, "Body": io.BytesIO(self.objects[(Key, VersionId)])}

    def delete_object(self, *, Key, VersionId=None, **kwargs):
        self.deleted.append(Key)
        self.objects.pop((Key, VersionId), None)


@pytest.fixture
async def setup(monkeypatch):
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        app_env="test",
        database_url=os.environ["DATABASE_URL"],
        jwt_secret_key="test-jwt-secret-key-32-chars-minimum!!",
        s3_documents_bucket="synthetic-private",
        s3_document_key_prefix="staging",
        employer_portal_base_url="https://recipient.example.test",
    )
    storage = MemoryS3()
    monkeypatch.setattr("app.services.document_pack_storage.get_s3_client", lambda _: storage)
    async with factory() as session:
        owner = User(
            id=uuid4(),
            email=f"qa-{uuid4()}@example.test",
            full_name="Synthetic QA",
            role="user",
            is_active=True,
        )
        other = User(id=uuid4(), email=f"qa-{uuid4()}@example.test", role="user", is_active=True)
        session.add_all([owner, other])
        await session.flush()
        docs = []
        for person, kind in [(owner, "aadhaar"), (owner, "pan"), (other, "passport")]:
            key = f"staging/user-documents/{uuid4()}.pdf"
            meta = storage.put(key)
            doc = UserDocument(
                id=uuid4(),
                user_id=person.id,
                document_type=kind,
                object_key=key,
                original_filename="synthetic-qa.pdf",
                content_type="application/pdf",
                byte_size=meta["ContentLength"],
                checksum_sha256="a" * 64,
                verification_status="pending",
            )
            session.add(doc)
            docs.append(doc)
        await session.commit()
        owner_id, other_id = owner.id, other.id
        svc = DocumentSharePackService(session, settings)
        yield SimpleNamespace(
            session=session,
            factory=factory,
            settings=settings,
            storage=storage,
            svc=svc,
            owner=owner,
            other=other,
            docs=docs,
        )
        await session.rollback()
        # Only this fixture's synthetic users and their dependent records are removed.
        for person_id in (owner_id, other_id):
            await session.execute(
                delete(VerificationRequest).where(
                    VerificationRequest.requested_by_user_id == person_id
                )
            )
            await session.execute(
                delete(Employment).where(Employment.created_by_user_id == person_id)
            )
            await session.execute(text("DELETE FROM users WHERE id=:id"), {"id": person_id})
        await session.commit()
    await engine.dispose()


async def payload_for(ctx, *, count=1):
    docs, _ = await ctx.svc.sources.list(ctx.owner.id)
    return DocumentPackCreate(
        purpose="  Synthetic QA onboarding  ",
        expiry_days=7,
        items=[
            doc.model_dump(include={"source_type", "source_id", "selection_version"})
            for doc in docs[:count]
        ],
    )


def token_from(created):
    return parse_qs(urlsplit(created.share_url).fragment)["token"][0]


@pytest.mark.parametrize(
    "kind",
    [
        "aadhaar",
        "pan",
        "passport",
        "driving_license",
        "voter_id",
        "birth_certificate",
        "address_proof",
        "government_id",
    ],
)
def test_precise_identity_and_legacy_upload_contract(kind):
    request = UserDocumentUploadIntentRequest(
        document_type=kind, original_filename="qa.pdf", content_type="application/pdf", byte_size=20
    )
    assert request.document_type.value == kind
    assert "verification_status" not in type(request).model_fields


@pytest.mark.parametrize(
    "patch",
    [
        {"items": []},
        {"purpose": "   "},
        {"purpose": "x" * 121},
        {"expiry_days": 0},
        {"expiry_days": 31},
        {"expiry_days": None},
        {"permissions": {"include_profile": True}},
        {
            "items": [
                {
                    "source_type": "verification",
                    "source_id": str(uuid4()),
                    "selection_version": "a" * 64,
                }
            ]
        },
    ],
)
def test_creation_validation(patch):
    body = {
        "purpose": "QA",
        "expiry_days": 7,
        "items": [
            {"source_type": "vault", "source_id": str(uuid4()), "selection_version": "a" * 64}
        ],
    }
    with pytest.raises(ValidationError):
        DocumentPackCreate(**(body | patch))


def test_expiry_and_purpose_are_required_duplicate_sources_rejected():
    item = {"source_type": "vault", "source_id": uuid4(), "selection_version": "a" * 64}
    for body in [
        {"items": [item]},
        {"purpose": "QA", "items": [item]},
        {"purpose": "QA", "expiry_days": 7, "items": [item, item]},
    ]:
        with pytest.raises(ValidationError):
            DocumentPackCreate(**body)


async def test_hash_only_history_privacy_exact_selection(setup):
    c = setup
    created = await c.svc.create(c.owner.id, await payload_for(c))
    token = token_from(created)
    row = await c.svc.owned(c.owner.id, created.public_id)
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert len(row.items) == 1
    assert row.purpose == "Synthetic QA onboarding"
    history, total = await c.svc.history(c.owner.id)
    assert total == 1 and "share_url" not in history[0].model_dump()
    public = await c.svc.recipient(token)
    assert set(public.model_dump()) == {"purpose", "expires_at", "document_count", "items"}
    assert set(public.items[0].model_dump()) == {
        "public_id",
        "category",
        "title",
        "context",
        "filename",
        "content_type",
        "byte_size",
    }
    assert (await c.svc.owned(c.owner.id, row.public_id)).view_count == 1
    assert "synthetic-private" not in public.model_dump_json()
    with pytest.raises(NotFoundError):
        await c.svc.public_item(token, uuid4())
    with pytest.raises(NotFoundError):
        await c.svc.owned(c.other.id, row.public_id)


async def test_other_owner_and_changed_selection_atomic(setup):
    c = setup
    owner_id, other_id = c.owner.id, c.other.id
    payload = await payload_for(c)
    with pytest.raises(NotFoundError):
        await c.svc.create(other_id, payload)
    assert await c.session.scalar(select(func.count()).select_from(DocumentSharePack)) == 0
    payload.items[0].selection_version = "f" * 64
    with pytest.raises(ValidationAppError):
        await c.svc.create(owner_id, payload)
    assert not c.storage.deleted


async def test_source_overwrite_and_detach_keep_exact_snapshot(setup):
    c = setup
    payload = await payload_for(c)
    source_id = payload.items[0].source_id
    source = next(doc for doc in c.docs if doc.id == source_id)
    original = c.storage.objects[(source.object_key, None)]
    created = await c.svc.create(c.owner.id, payload)
    token = token_from(created)
    pack = await c.svc.owned(c.owner.id, created.public_id)
    assert pack.items[0].owns_snapshot
    c.storage.put(source.object_key, b"replacement bytes")
    source.deleted_at = datetime.now(UTC)
    await c.session.commit()
    grant = await c.svc.download_url(token, pack.items[0].public_id)
    query = parse_qs(urlsplit(grant["download_url"]).query)
    chunks, headers, mime = await c.svc.content(
        token, pack.items[0].public_id, int(query["expires"][0]), query["signature"][0]
    )
    assert b"".join(chunks) == original
    assert "no-store" in headers["Cache-Control"] and mime == "application/pdf"
    assert "amazonaws" not in grant["download_url"]
    assert await cleanup_document_pack_snapshots(c.session, c.settings) == 0


async def test_revoke_is_idempotent_blocks_preissued_file_grant_and_cleanup_safe(setup):
    c = setup
    created = await c.svc.create(c.owner.id, await payload_for(c))
    token = token_from(created)
    item = created.items[0].public_id
    grant = await c.svc.download_url(token, item)
    query = parse_qs(urlsplit(grant["download_url"]).query)
    first = await c.svc.revoke(c.owner.id, created.public_id)
    second = await c.svc.revoke(c.owner.id, created.public_id)
    assert first.revoked_at == second.revoked_at
    with pytest.raises(NotFoundError):
        await c.svc.content(token, item, int(query["expires"][0]), query["signature"][0])
    assert await cleanup_document_pack_snapshots(c.session, c.settings) == 1
    assert all("/document-share-packs/" in key for key in c.storage.deleted)
    assert all((doc.object_key, None) in c.storage.objects for doc in c.docs)
    assert (await c.svc.owned(c.owner.id, created.public_id)).items


async def test_expiry_unknown_disabled_owner_fail_closed(setup):
    c = setup
    created = await c.svc.create(c.owner.id, await payload_for(c))
    token = token_from(created)
    with pytest.raises(NotFoundError):
        await c.svc.resolve("unknown")
    c.owner.is_active = False
    await c.session.commit()
    with pytest.raises(NotFoundError):
        await c.svc.resolve(token)
    c.owner.is_active = True
    row = await c.svc.owned(c.owner.id, created.public_id)
    row.created_at = datetime.now(UTC) - timedelta(days=2)
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await c.session.commit()
    with pytest.raises(NotFoundError):
        await c.svc.resolve(token)
    assert c.svc.response(row).status == "expired"


async def test_deleted_superseded_pending_upload_not_selectable(setup):
    c = setup
    c.docs[0].superseded_at = datetime.now(UTC)
    c.docs[1].checksum_sha256 = ""
    await c.session.commit()
    docs, total = await c.svc.sources.list(c.owner.id)
    assert docs == [] and total == 0


async def test_versioned_reference_does_not_copy_bytes(setup):
    storage = DocumentPackStorage(setup.settings)
    binding = await storage.inspect(setup.docs[0].object_key)
    from dataclasses import replace

    versioned = replace(binding, version="immutable-version")
    assert await storage.snapshot(versioned, "unused") is versioned


async def test_missing_selected_object_rejected_without_partial_pack(setup):
    c = setup
    owner = c.owner.id
    payload = await payload_for(c)
    source = next(doc for doc in c.docs if doc.id == payload.items[0].source_id)
    c.storage.objects.pop((source.object_key, None))
    with pytest.raises(NotFoundError):
        await c.svc.create(owner, payload)
    assert await c.session.scalar(select(func.count()).select_from(DocumentSharePack)) == 0


async def test_cross_pack_items_and_tampered_download_grants_fail_closed(setup):
    c = setup
    first = await c.svc.create(c.owner.id, await payload_for(c))
    second = await c.svc.create(c.owner.id, await payload_for(c))
    token = token_from(first)
    with pytest.raises(NotFoundError):
        await c.svc.download_url(token, second.items[0].public_id)
    with pytest.raises(NotFoundError):
        await c.svc.revoke(c.other.id, first.public_id)
    item = first.items[0].public_id
    now = int(datetime.now(UTC).timestamp())
    for expiry, signature in [
        (now + 30, "0" * 64),
        (now - 1, c.svc.signature(token, item, now - 1)),
        (now + 600, c.svc.signature(token, item, now + 600)),
    ]:
        with pytest.raises(NotFoundError):
            await c.svc.content(token, item, expiry, signature)


async def test_route_auth_no_cache_and_no_expansion(setup):
    c = setup
    app.dependency_overrides[service_dependency] = lambda: c.svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            unauthorized = await client.get("/api/v1/document-share-packs")
            assert unauthorized.status_code == 401
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(
                id=c.owner.id, email="qa@example.test", role="user"
            )
            payload = await payload_for(c)
            created = await client.post(
                "/api/v1/document-share-packs", json=payload.model_dump(mode="json")
            )
            assert created.status_code == 201
            assert "no-store" in created.headers["cache-control"]
            pack_id = created.json()["public_id"]
            patch = await client.patch(
                f"/api/v1/document-share-packs/{pack_id}", json={"items": []}
            )
            assert patch.status_code == 405
            unknown = await client.get("/api/v1/public/document-share-packs/" + "z" * 43)
            assert unknown.status_code == 404
            assert "no-store" in unknown.headers["cache-control"]
    finally:
        app.dependency_overrides.pop(service_dependency, None)
        app.dependency_overrides.pop(get_current_user, None)


def test_migration_and_public_openapi_and_credential_redaction():
    migration = Path("alembic/versions/078_document_share_packs.py").read_text()
    assert 'revision = "078"' in migration and 'down_revision = "077"' in migration
    assert "alter_column" not in migration and "passport_share" not in migration
    api = app.openapi()
    assert "/api/v1/document-share-packs" in api["paths"]
    fields = api["components"]["schemas"]["PublicDocumentPack"]["properties"]
    assert set(fields) == {"purpose", "expires_at", "document_count", "items"}
    path = (
        "/api/v1/public/document-share-packs/"
        + "z" * 43
        + "/items/qa/content?signature="
        + "a" * 64
    )
    redacted = redact_request_credentials(path)
    assert "z" * 43 not in redacted and "a" * 64 not in redacted
    assert redacted.count("[REDACTED]") == 2
