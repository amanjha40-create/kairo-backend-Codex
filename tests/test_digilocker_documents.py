import base64
import hmac
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from digilocker_helpers import settings
from pydantic import SecretStr

from app.api.v1.routes.digilocker import get_document_service
from app.auth.deps import CurrentUser, get_current_user
from app.exceptions import NotFoundError, ServiceUnavailableError, ValidationAppError
from app.integrations.digilocker.documents import (
    FILE_URL,
    ISSUED_URL,
    MAX_FILE_BYTES,
    DigiLockerDocuments,
    DocumentReferences,
    RetrievedDocument,
    normalize_items,
)
from app.integrations.digilocker.provider import ProviderError
from app.main import app
from app.services.digilocker_document_service import DigiLockerDocumentService


def item(doctype="PANCR"):
    return dict(
        name="Synthetic document",
        type="file",
        date="2026-01-01",
        mime="application/pdf",
        uri=f"in.test-{doctype}-SYNTHETIC",
        doctype=doctype,
        issuerid="in.test",
        issuer="Synthetic issuer",
        description="Test",
    )


def context():
    return SimpleNamespace(
        user_id=uuid4(),
        id=uuid4(),
        status="active",
        token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        consent_valid_until=None,
        encrypted_access_token={"synthetic": "ciphertext"},
    )


def test_normalize_multiple_none_and_doctype_not_name():
    assert normalize_items({"items": []}) == ([], 0)
    records, bad = normalize_items(
        {"items": [item(), item("DRVLC"), item(), {**item("OTHER"), "name": "PAN"}]}
    )
    assert len(records) == 4 and bad == 0
    assert [i["supported"] for i in records] == [True, True, True, False]


@pytest.mark.parametrize("payload", [None, [], {}, {"items": {}}, {"items": [item()] * 501}])
def test_malformed_list(payload):
    with pytest.raises(ProviderError):
        normalize_items(payload)


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        {**item(), "uri": "https://evil.invalid"},
        {**item(), "uri": "../anything"},
        {**item(), "doctype": None},
        {**item(), "issuerid": None},
        {**item(), "mime": {}},
    ],
)
def test_bad_rows_skipped(bad):
    records, malformed = normalize_items({"items": [bad, item()]})
    assert len(records) == malformed == 1


def test_reference_bound_to_owner_connection_credentials_and_ttl():
    config, connection, now = settings(), context(), datetime.now(UTC)
    refs = DocumentReferences(config, connection, now)
    record = normalize_items({"items": [item()]})[0][0]
    ref = refs.issue(record)
    assert record["uri"] not in ref
    assert refs.open(ref) == record
    for field, value in [
        ("user_id", uuid4()),
        ("id", uuid4()),
        ("encrypted_access_token", {"new": "credential"}),
    ]:
        other = SimpleNamespace(**{**vars(connection), field: value})
        with pytest.raises(ProviderError):
            DocumentReferences(config, other, now).open(ref)
    with pytest.raises(ProviderError):
        DocumentReferences(config, connection, now + timedelta(seconds=600)).open(ref)
    with pytest.raises(ProviderError):
        refs.open(ref[:-5] + "abcde")
    with pytest.raises(ProviderError):
        refs.open(refs.issue({**record, "doctype": "OTHER", "supported": False}))


async def test_provider_wire_and_valid_hmac():
    config = settings()
    content = b"%PDF-synthetic test bytes"
    digest = base64.b64encode(
        hmac.digest(config.digilocker_client_secret.get_secret_value().encode(), content, "sha256")
    ).decode()
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer synthetic-access"
        assert request.headers["accept-encoding"] == "identity"
        if request.url.path.endswith("/issued"):
            assert str(request.url) == ISSUED_URL
            return httpx.Response(200, json={"items": [item()]})
        assert str(request.url) == FILE_URL + item()["uri"]
        assert not request.url.query
        return httpx.Response(
            200, content=content, headers={"hmac": digest, "Content-Type": "application/PDF"}
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), auth=("ignored", "ignored")
    ) as client:
        provider = DigiLockerDocuments(config, client=client)
        token = SecretStr("synthetic-access")
        assert len((await provider.issued(token))[0]) == 1
        doc = await provider.retrieve(token, item()["uri"])
        assert doc.content == content and doc.mime == "application/pdf"
    assert len(calls) == 2


@pytest.mark.parametrize(
    "mode",
    [
        "missing",
        "bad",
        "hex",
        "oversize",
        "compressed",
        "empty",
        "html",
        "401",
        "403",
        "404",
        "500",
        "redirect",
        "timeout",
        "json",
    ],
)
async def test_provider_failures_closed_and_safe(mode, caplog):
    config = settings()
    content = b"synthetic-private-content"
    if mode == "oversize":
        content = b"x" * (MAX_FILE_BYTES + 1)
    if mode == "empty":
        content = b""
    headers = {"Content-Type": "text/html" if mode == "html" else "application/pdf"}
    digest = hmac.digest(
        config.digilocker_client_secret.get_secret_value().encode(), content, "sha256"
    )
    headers["hmac"] = base64.b64encode(digest).decode()
    if mode == "missing":
        del headers["hmac"]
    if mode == "bad":
        headers["hmac"] = base64.b64encode(b"x" * 32).decode()
    if mode == "hex":
        headers["hmac"] = digest.hex()
    if mode == "compressed":
        headers["Content-Encoding"] = "unknown"
    status = int(mode) if mode.isdigit() else 302 if mode == "redirect" else 200

    def handler(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("private details")
        return httpx.Response(status, content=content, headers=headers)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = DigiLockerDocuments(config, client=client)
        with pytest.raises(ProviderError):
            if mode == "json":
                await provider.issued(SecretStr("synthetic-access"))
            else:
                await provider.retrieve(SecretStr("synthetic-access"), item()["uri"])
    assert "synthetic-private-content" not in caplog.text
    assert "synthetic-access" not in caplog.text
    assert item()["uri"] not in caplog.text


def service_context():
    config, row = settings(), context()
    session = SimpleNamespace(rollback=AsyncMock(), commit=AsyncMock())
    docs = SimpleNamespace(
        issued=AsyncMock(return_value=normalize_items({"items": [item(), item("OTHER")]})),
        retrieve=AsyncMock(return_value=RetrievedDocument(b"private", "application/pdf")),
    )
    service = DigiLockerDocumentService(session, config, SimpleNamespace(), documents=docs)
    service._owner = AsyncMock()
    service._connection = AsyncMock(return_value=row)
    service._decrypt = lambda *_: SecretStr("synthetic-access")
    return service, row, session, docs


async def test_service_metadata_only_no_commit_refresh_revoke_or_file_storage():
    service, row, session, docs = service_context()
    listing = await service.issued(row.user_id)
    assert listing["count"] == 2 and "uri" not in listing["items"][0]
    assert listing["items"][1]["reference"] is None
    result = await service.retrieve(row.user_id, listing["items"][0]["reference"])
    assert result["integrity"] == "verified" and result["source"] == "digilocker"
    assert "private" not in json.dumps(result)
    assert "synthetic-access" not in json.dumps(result)
    session.commit.assert_not_awaited()
    assert session.rollback.await_count == 2
    assert docs.retrieve.await_count == 1
    service._owner.assert_awaited_with(row.user_id)
    service._connection.assert_awaited_with(row.user_id)


@pytest.mark.parametrize(
    "mode", ["expired", "consent", "disconnected", "absent", "disabled", "deleted"]
)
async def test_service_unavailable_never_calls_provider_or_mutates(mode):
    service, row, session, docs = service_context()
    if mode == "expired":
        row.token_expires_at = datetime.now(UTC)
    if mode == "consent":
        row.consent_valid_until = datetime.now(UTC)
    if mode == "disconnected":
        row.status = "disconnected"
    if mode == "absent":
        service._connection.return_value = None
    if mode == "disabled":
        service.settings.digilocker_enabled = False
    if mode == "deleted":
        service._owner.side_effect = NotFoundError("Account unavailable")
    with pytest.raises((ValidationAppError, ServiceUnavailableError, NotFoundError)):
        await service.issued(row.user_id)
    docs.issued.assert_not_awaited()
    docs.retrieve.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_service_reference_cross_user_and_provider_error():
    service, row, session, docs = service_context()
    reference = (await service.issued(row.user_id))["items"][0]["reference"]
    row.user_id = uuid4()
    with pytest.raises(NotFoundError):
        await service.retrieve(row.user_id, reference)
    docs.retrieve.assert_not_awaited()
    docs.issued.side_effect = ProviderError("invalid_token")
    with pytest.raises(ValidationAppError):
        await service.issued(row.user_id)
    session.commit.assert_not_awaited()


async def test_routes_auth_owner_scope_no_store_and_no_owner_override():
    previous = app.dependency_overrides.copy()
    fake = SimpleNamespace(
        issued=AsyncMock(return_value={"items": [], "count": 0, "malformed_count": 0}),
        retrieve=AsyncMock(return_value={"integrity": "verified"}),
    )
    app.dependency_overrides[get_document_service] = lambda: fake
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            base = "/api/v1/integrations/digilocker/documents"
            assert (await client.get(base + "/issued")).status_code == 401
            assert (
                await client.post(base + "/retrieve", json={"reference": "opaque"})
            ).status_code == 401
            user = CurrentUser(id=uuid4(), email="synthetic@example.invalid", role="user")
            app.dependency_overrides[get_current_user] = lambda: user
            result = await client.get(base + "/issued")
            assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
            fake.issued.assert_awaited_once_with(user.id)
            result = await client.post(base + "/retrieve", json={"reference": "opaque"})
            assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
            fake.retrieve.assert_awaited_once_with(user.id, "opaque")
            assert (
                await client.post(
                    base + "/retrieve", json={"reference": "opaque", "user_id": str(uuid4())}
                )
            ).status_code == 422
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
