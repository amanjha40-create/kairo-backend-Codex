import asyncio
import base64
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import delete, func, inspect, select
from test_digilocker_documents import item
from test_digilocker_lifecycle import harness  # noqa: F401

from app.api.v1.routes.digilocker import get_identity_service
from app.auth.deps import CurrentUser, get_current_user
from app.db.session import async_session_factory, engine
from app.exceptions import ServiceUnavailableError, ValidationAppError
from app.integrations.digilocker.documents import RetrievedDocument, normalize_items
from app.integrations.digilocker.identity import match_document
from app.integrations.digilocker.provider import ProviderError
from app.main import app
from app.models import (
    DigiLockerConnection,
    DigiLockerIdentityVerification,
    TrustScoreSnapshot,
    User,
    UserDocument,
)
from app.schemas.account_deletion import AccountDeletionRequest
from app.services.account_deletion_service import AccountDeletionService
from app.services.digilocker_identity_service import (
    DigiLockerIdentityService,
    reference_fingerprint,
)

TODAY = date(2026, 9, 24)
DOB = date(1990, 1, 2)


def certificate(doctype="PANCR", name="Test Candidate", dob="02-01-1990", extra="", expiry=""):
    return RetrievedDocument(
        (
            f'<Certificate type="{doctype}" number="SYNTHETIC-PRIVATE-ID" status="A" {expiry}>'
            f'<IssuedTo><Person name="{name}" dob="{dob}"/>{extra}</IssuedTo></Certificate>'
        ).encode(),
        "application/xml",
    )


@pytest.mark.parametrize("doctype", ["PANCR", "DRVLC"])
@pytest.mark.parametrize(
    "name,dob,result",
    [
        ("Test Candidate", DOB, "VERIFIED_MATCH"),
        ("  TEST   Candidate ", DOB, "VERIFIED_MATCH"),
        ("Other Candidate", DOB, "MISMATCH"),
        ("Test Candidate", date(1980, 1, 1), "MISMATCH"),
        ("Test Candidate", None, "PARTIAL_MATCH"),
        (None, DOB, "PARTIAL_MATCH"),
        (None, None, "UNABLE_TO_VERIFY"),
    ],
)
def test_conservative_matching(doctype, name, dob, result):
    assert match_document(certificate(doctype), doctype, name, dob, TODAY).result == result


@pytest.mark.parametrize(
    "document",
    [
        RetrievedDocument(b"broken", "application/xml"),
        RetrievedDocument(b"<Certificate/>", "application/pdf"),
        RetrievedDocument(
            b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><Certificate>&e;</Certificate>',
            "application/xml",
        ),
        certificate("DRVLC"),
        certificate(dob="1990"),
        certificate(dob="31-02-1990"),
        certificate(dob="02-01-2090"),
        certificate(extra='<Person name="Test Candidate" dob="02-01-1990"/>'),
        RetrievedDocument(b"x" * (1024 * 1024 + 1), "application/xml"),
    ],
)
def test_fail_closed_parse(document):
    assert (
        match_document(document, "PANCR", "Test Candidate", DOB, TODAY).result == "UNABLE_TO_VERIFY"
    )


@pytest.mark.parametrize(
    "expiry,result",
    [
        ("23-09-2026", "UNABLE_TO_VERIFY"),
        ("24-09-2026", "VERIFIED_MATCH"),
        ("24-09-2030", "VERIFIED_MATCH"),
    ],
)
def test_dl_currentness(expiry, result):
    doc = certificate("DRVLC", expiry=f'expiryDate="{expiry}"')
    assert match_document(doc, "DRVLC", "Test Candidate", DOB, TODAY).result == result


def test_standard_base64_envelope():
    content = base64.b64encode(certificate().content).decode()
    doc = RetrievedDocument(
        (
            '<PullDocResponse><ResponseStatus status="1"/><DocDetails><DataContent>'
            f"{content}</DataContent></DocDetails></PullDocResponse>"
        ).encode(),
        "text/xml",
    )
    assert match_document(doc, "PANCR", "Test Candidate", DOB, TODAY).result == "VERIFIED_MATCH"


@pytest.mark.parametrize(
    "document,category",
    [
        (RetrievedDocument(b"broken", "application/xml"), "MALFORMED_XML"),
        (
            RetrievedDocument(b'<Certificate type="PANCR"/>', "application/xml"),
            "MISSING_REQUIRED_FIELDS",
        ),
        (certificate(name="", dob=""), "IDENTITY_FIELDS_NOT_AVAILABLE"),
        (certificate(dob="invalid"), "PROVIDER_RESPONSE_INVALID"),
        (certificate("DRVLC"), "PROVIDER_RESPONSE_INVALID"),
        (RetrievedDocument(b"%PDF-private-canary", "application/pdf"), "UNSUPPORTED_MIME"),
    ],
)
def test_safe_parse_categories(document, category):
    result = match_document(document, "PANCR", "Test Candidate", DOB, TODAY)
    assert result.result == "UNABLE_TO_VERIFY" and result.category == category


@pytest.fixture
async def identity(harness):  # noqa: F811 - imported pytest fixture
    h = harness
    await h.activate()
    async with async_session_factory() as session:
        user = await session.get(User, h.ids[0])
        user.full_name, user.date_of_birth = "Test Candidate", DOB
        await session.commit()
    docs = SimpleNamespace(
        issued=AsyncMock(return_value=normalize_items({"items": [item(), item("DRVLC")]})),
        retrieve=AsyncMock(
            side_effect=lambda token, uri, **kwargs: certificate(
                "DRVLC" if "DRVLC" in uri else "PANCR"
            )
        ),
    )

    async def call(types=None, user=None, **kwargs):
        async with async_session_factory() as session:
            service = DigiLockerIdentityService(session, h.config, h.redis, documents=docs)
            if types is None:
                return await service.history(user or h.ids[0])
            return await service.verify(
                user or h.ids[0],
                types,
                consent=kwargs.get("consent", True),
                consent_version=kwargs.get("version", "v1"),
            )

    return SimpleNamespace(h=h, docs=docs, call=call)


async def test_persistence_privacy_repeat_concurrency_no_score_or_profile_mutation(identity):
    t = identity
    async with async_session_factory() as session:
        user = await session.get(User, t.h.ids[0])
        revision = user.updated_at
        scores = await session.scalar(
            select(func.count())
            .select_from(TrustScoreSnapshot)
            .where(TrustScoreSnapshot.user_id == user.id)
        )
    results = await asyncio.gather(t.call(["PANCR", "DRVLC"]), t.call(["PANCR", "DRVLC"]))
    assert all(r["identity_verified"] and len(r["items"]) == 2 for r in results)
    assert {r["id"] for r in results[0]["items"]} == {r["id"] for r in results[1]["items"]}
    async with async_session_factory() as session:
        rows = (
            await session.scalars(
                select(DigiLockerIdentityVerification).where(
                    DigiLockerIdentityVerification.user_id == t.h.ids[0]
                )
            )
        ).all()
        assert len(rows) == 2
        serialized = str(
            [{c.name: getattr(row, c.name) for c in row.__table__.columns} for row in rows]
        )
        assert all(
            secret not in serialized
            for secret in ["SYNTHETIC-PRIVATE-ID", item()["uri"], "<Certificate", "Test Candidate"]
        )
        assert all(
            row.consent_purpose == "identity_verification" and row.consent_version == "v1"
            for row in rows
        )
        assert rows[0].source_connection_id is not None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(UserDocument)
                .where(UserDocument.user_id == t.h.ids[0])
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(TrustScoreSnapshot)
                .where(TrustScoreSnapshot.user_id == t.h.ids[0])
            )
            == scores
        )
        assert (await session.get(User, t.h.ids[0])).updated_at == revision
    assert (await t.call())["identity_verified"]
    assert (await t.call(user=t.h.ids[1])) == {"items": [], "identity_verified": False}


async def test_xml_preferred_for_both_types_updates_existing_rows_with_safe_diagnostics(
    identity, caplog
):
    t = identity
    t.docs.retrieve.side_effect = None
    t.docs.retrieve.return_value = RetrievedDocument(b"%PDF-private-canary", "application/pdf")
    caplog.set_level("INFO", logger="app.services.digilocker_identity_service")
    first = await t.call(["PANCR", "DRVLC"])
    assert all(row["match_result"] == "UNABLE_TO_VERIFY" for row in first["items"])
    assert all(call.kwargs == {"xml": False} for call in t.docs.retrieve.await_args_list)
    assert all(
        r.parse_category == "UNSUPPORTED_MIME"
        for r in caplog.records
        if r.message == "digilocker_identity_format"
    )
    t.docs.issued.return_value = normalize_items(
        {
            "items": [
                {**item(d), "mime": ["application/pdf", "application/xml"]}
                for d in ["PANCR", "DRVLC"]
            ]
        }
    )
    t.docs.retrieve.reset_mock()
    t.docs.retrieve.side_effect = lambda token, uri, **kwargs: certificate(
        "DRVLC" if "DRVLC" in uri else "PANCR"
    )
    caplog.clear()
    second = await t.call(["PANCR", "DRVLC"])
    assert second["identity_verified"]
    assert {row["id"] for row in second["items"]} == {row["id"] for row in first["items"]}
    assert all(call.kwargs == {"xml": True} for call in t.docs.retrieve.await_args_list)
    assert len((await t.call())["items"]) == 2
    diagnostics = [r for r in caplog.records if r.message == "digilocker_identity_format"]
    assert len(diagnostics) == 2
    for record in diagnostics:
        assert record.document_type in {"PANCR", "DRVLC"}
        assert record.metadata_mimes == ["application/pdf", "application/xml"]
        assert record.retrieval_endpoint == "xml" and record.parser_selected == "xml"
        assert record.response_content_type == "application/xml" and record.response_bytes > 0
        assert record.hmac_result == "PASS" and record.parse_category == "XML_SUPPORTED"
    serialized = str([r.__dict__ for r in diagnostics])
    for secret in [
        "Test Candidate",
        "02-01-1990",
        "SYNTHETIC-PRIVATE-ID",
        "<Certificate",
        item()["uri"],
        "private-canary",
    ]:
        assert secret not in serialized


async def test_integrity_failure_never_reaches_parser(identity, monkeypatch, caplog):
    def forbidden(*args):
        raise AssertionError("parser must not run")

    monkeypatch.setattr("app.services.digilocker_identity_service.match_document", forbidden)
    identity.docs.retrieve.side_effect = ProviderError("integrity_failed")
    caplog.set_level("INFO", logger="app.services.digilocker_identity_service")
    result = await identity.call(["PANCR"])
    assert result["items"][0]["match_result"] == "UNABLE_TO_VERIFY"
    record = next(r for r in caplog.records if r.message == "digilocker_identity_format")
    assert record.hmac_result == "FAIL" and record.parser_selected == "none"


@pytest.mark.parametrize(
    "types,consent,version",
    [
        ([], True, "v1"),
        (["AADHAR"], True, "v1"),
        (["PANCR", "PANCR"], True, "v1"),
        (["PANCR"], False, "v1"),
        (["PANCR"], True, "v2"),
    ],
)
async def test_selection_consent_required_before_provider(identity, types, consent, version):
    with pytest.raises(ValidationAppError):
        await identity.call(types, consent=consent, version=version)
    identity.docs.issued.assert_not_awaited()
    identity.docs.retrieve.assert_not_awaited()


async def test_inventory_owner_and_ambiguity(identity):
    t = identity
    with pytest.raises(ValidationAppError):
        await t.call(["PANCR"], user=t.h.ids[1])
    t.docs.issued.return_value = normalize_items(
        {"items": [item(), {**item(), "uri": "in.test-PANCR-OTHER"}]}
    )
    with pytest.raises(ValidationAppError):
        await t.call(["PANCR"])
    t.docs.retrieve.assert_not_awaited()
    assert not (await t.call())["items"]


async def test_expired_connection_no_refresh(identity):
    await identity.h.alter(token_expires_at=datetime.now(UTC) - timedelta(seconds=1))
    with pytest.raises(ValidationAppError):
        await identity.call(["PANCR"])
    identity.docs.issued.assert_not_awaited()
    identity.h.fake.refresh_access_token.assert_not_awaited()


async def test_hmac_failure_persisted_only_as_failure(identity):
    t = identity
    await t.call(["PANCR"])
    t.docs.retrieve.side_effect = ProviderError("integrity_failed")
    result = await t.call(["PANCR"])
    assert not result["identity_verified"]
    assert result["items"][0]["integrity_result"] == "failed"
    assert result["items"][0]["match_result"] == "UNABLE_TO_VERIFY"
    assert result["items"][0]["verified_at"] is None


async def test_timeout_rolls_back_entire_selection(identity):
    identity.docs.retrieve.side_effect = [certificate(), ProviderError("transport_error")]
    with pytest.raises(ServiceUnavailableError):
        await identity.call(["PANCR", "DRVLC"])
    assert not (await identity.call())["items"]


async def test_profile_edit_invalidates_current_badge_but_preserves_history(identity):
    await identity.call(["PANCR"])
    async with async_session_factory() as session:
        user = await session.get(User, identity.h.ids[0])
        user.full_name = "Changed Candidate"
        await session.commit()
    result = await identity.call()
    assert not result["identity_verified"]
    assert result["items"][0]["match_result"] == "VERIFIED_MATCH"


async def test_disconnect_history_set_null_and_account_erasure(identity):
    t = identity
    await t.call(["PANCR"])
    await t.h.call("disconnect")
    assert (await t.call())["identity_verified"]
    async with async_session_factory() as session:
        await session.execute(
            delete(DigiLockerConnection).where(DigiLockerConnection.user_id == t.h.ids[0])
        )
        await session.commit()
        row = await session.scalar(
            select(DigiLockerIdentityVerification).where(
                DigiLockerIdentityVerification.user_id == t.h.ids[0]
            )
        )
        assert row.source_connection_id is None
    async with async_session_factory() as session:
        await AccountDeletionService(session, t.h.config, t.h.redis).delete_candidate_account(
            t.h.ids[0], AccountDeletionRequest(confirm="DELETE", current_password="TestOnly123!")
        )
    async with async_session_factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DigiLockerIdentityVerification)
                .where(DigiLockerIdentityVerification.user_id == t.h.ids[0])
            )
            == 0
        )


async def test_hard_user_delete_cascades(identity):
    await identity.call(["PANCR"])
    async with async_session_factory() as session:
        await session.execute(delete(User).where(User.id == identity.h.ids[0]))
        await session.commit()
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DigiLockerIdentityVerification)
                .where(DigiLockerIdentityVerification.user_id == identity.h.ids[0])
            )
            == 0
        )


def test_fingerprint_stable_and_domain_separated():
    value = reference_fingerprint("PANCR", item()["uri"])
    assert len(value) == 64 and value == reference_fingerprint("PANCR", item()["uri"])
    assert value != reference_fingerprint("DRVLC", item()["uri"])


async def test_081_metadata_constraints():
    import ast
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["083"]
    migration = script.get_revision("081")
    assert migration.down_revision == "080"
    tree = ast.parse(Path(migration.path).read_text())
    operations = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "op"
    ]
    assert sorted(node.func.attr for node in operations) == [
        "create_index",
        "create_index",
        "create_table",
        "drop_table",
    ]
    assert all(
        "digilocker_identity_verifications" in ast.literal_eval(node.args[0]) for node in operations
    )

    def check(connection):
        inspector = inspect(connection)
        table = DigiLockerIdentityVerification.__table__
        assert {c["name"]: c["nullable"] for c in inspector.get_columns(table.name)} == {
            c.name: c.nullable for c in table.columns
        }
        assert {
            f["referred_table"]: f["options"]["ondelete"]
            for f in inspector.get_foreign_keys(table.name)
        } == {"users": "CASCADE", "digilocker_connections": "SET NULL"}
        assert len(inspector.get_check_constraints(table.name)) == 8
        assert [u["column_names"] for u in inspector.get_unique_constraints(table.name)] == [
            ["user_id", "document_type", "provider_reference_fingerprint"]
        ]

    async with engine.connect() as connection:
        await connection.run_sync(check)


async def test_routes_auth_controlled_input_and_no_cache():
    from uuid import uuid4

    previous = app.dependency_overrides.copy()
    fake = SimpleNamespace(
        trust=AsyncMock(return_value={"state": "unverified", "sources": [], "private": "CANARY"}),
        history=AsyncMock(return_value={"items": [], "identity_verified": False}),
        verify=AsyncMock(return_value={"items": [], "identity_verified": False}),
    )
    app.dependency_overrides[get_identity_service] = lambda: fake
    base = "/api/v1/integrations/digilocker/identity"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            assert (await client.get(base + "/verifications")).status_code == 401
            assert (await client.get(base + "/trust")).status_code == 401
            assert (await client.post(base + "/verify", json={})).status_code == 401
            user = CurrentUser(id=uuid4(), email="synthetic@example.invalid", role="user")
            app.dependency_overrides[get_current_user] = lambda: user
            response = await client.get(base + "/trust")
            assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
            assert response.json() == {"state": "unverified", "sources": []}
            fake.trust.assert_awaited_once_with(user.id)
            for body in [
                {"document_types": ["AADHAAR"], "consent": True, "consent_version": "v1"},
                {"document_types": ["PANCR"], "consent": "true", "consent_version": "v1"},
                {
                    "document_types": ["PANCR"],
                    "consent": True,
                    "consent_version": "v1",
                    "uri": "forbidden",
                },
            ]:
                assert (await client.post(base + "/verify", json=body)).status_code == 422
            fake.verify.assert_not_awaited()
            response = await client.post(
                base + "/verify",
                json={"document_types": ["PANCR"], "consent": True, "consent_version": "v1"},
            )
            assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
            fake.verify.assert_awaited_once_with(
                user.id, ["PANCR"], consent=True, consent_version="v1"
            )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
