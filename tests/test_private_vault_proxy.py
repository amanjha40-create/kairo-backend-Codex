"""Owner-only proxy exercises real ownership queries and the shared storage adapter."""

from datetime import UTC, datetime
from unittest.mock import Mock
from urllib.parse import unquote

from httpx import ASGITransport, AsyncClient
import pytest

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_user_document_service
from app.main import app
from app.schemas.user_document import UserDocumentResponse
from app.services.user_document_service import UserDocumentService
from test_document_share_packs import setup as document_pack_setup

setup = document_pack_setup


@pytest.mark.parametrize("mime", ["application/pdf", "image/jpeg", "image/png", "image/webp"])
async def test_owner_proxy_and_legacy_metadata_never_return_storage_location(
    setup, monkeypatch, mime
):
    c = setup
    doc = c.docs[0]
    doc.content_type = mime
    doc.original_filename = "../private\\safe\r\nname.pdf"
    await c.session.commit()
    original_head = c.storage.head_object
    monkeypatch.setattr(
        c.storage, "head_object", lambda **kw: {**original_head(**kw), "ContentType": mime}
    )
    svc = UserDocumentService(c.session, c.settings)
    app.dependency_overrides[get_user_document_service] = lambda: svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            url = f"/api/v1/user-documents/{doc.id}/content"
            assert (await client.get(url)).status_code == 401
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(
                id=c.owner.id, email="qa@example.test", role="user"
            )
            response = await client.get(url)
            assert response.status_code == 200
            assert response.content == b"%PDF-synthetic harmless QA"
            assert response.headers["content-type"] == mime
            assert response.headers["x-content-type-options"] == "nosniff"
            assert "no-store" in response.headers["cache-control"]
            assert "private" in response.headers["cache-control"]
            assert "sandbox" in response.headers["content-security-policy"]
            disposition = unquote(response.headers["content-disposition"])
            assert "safename.pdf" in disposition
            assert "\r" not in disposition and "\n" not in disposition and "../" not in disposition
            assert "location" not in response.headers
            metadata = await client.get(f"/api/v1/user-documents/{doc.id}/download-url")
            assert metadata.status_code == 200
            assert metadata.json()["download_url"] == url
            assert metadata.json()["expires_in_seconds"] == 0
            safe_output = (
                metadata.text
                + str(dict(response.headers))
                + UserDocumentResponse.model_validate(doc).model_dump_json()
            )
            assert doc.object_key not in safe_output
            assert c.settings.s3_documents_bucket not in safe_output
            assert "amazonaws.com" not in safe_output
    finally:
        app.dependency_overrides.pop(get_user_document_service, None)
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.parametrize("unavailable", ["other_owner", "deleted", "incomplete", "unsafe_mime"])
async def test_unavailable_fails_before_any_storage_lookup(setup, monkeypatch, unavailable):
    c = setup
    doc = c.docs[0]
    if unavailable == "deleted":
        doc.deleted_at = datetime.now(UTC)
    elif unavailable == "incomplete":
        doc.checksum_sha256 = ""
    elif unavailable == "unsafe_mime":
        doc.content_type = "text/html"
    await c.session.commit()
    lookup = Mock(side_effect=AssertionError("Storage must not be queried"))
    monkeypatch.setattr(c.storage, "head_object", lookup)
    app.dependency_overrides[get_user_document_service] = lambda: UserDocumentService(
        c.session, c.settings
    )
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=c.other.id if unavailable == "other_owner" else c.owner.id,
        email="qa@example.test",
        role="user",
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for suffix in ("content", "download-url"):
                response = await client.get(f"/api/v1/user-documents/{doc.id}/{suffix}")
                assert response.status_code == 404
                assert doc.object_key not in response.text
        lookup.assert_not_called()
    finally:
        app.dependency_overrides.pop(get_user_document_service, None)
        app.dependency_overrides.pop(get_current_user, None)


async def test_missing_or_changed_storage_object_fails_closed(setup):
    from app.exceptions import NotFoundError

    c = setup
    svc = UserDocumentService(c.session, c.settings)
    c.docs[0].byte_size += 1
    with pytest.raises(NotFoundError):
        await svc.content(c.owner.id, c.docs[0].id)
    c.storage.objects.clear()
    with pytest.raises(NotFoundError):
        await svc.content(c.owner.id, c.docs[0].id)


def test_content_openapi_has_no_bearer_file_url_contract():
    route = app.openapi()["paths"]["/api/v1/user-documents/{document_id}/content"]["get"]
    assert route["security"]
    assert route["responses"]["200"]["content"]["application/pdf"]["schema"]["format"] == "binary"
