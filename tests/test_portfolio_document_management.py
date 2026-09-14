from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_portfolio_service
from app.exceptions import NotFoundError
from app.main import app
from app.models.portfolio import PortfolioItem
from app.schemas.portfolio import PortfolioItemUpdateRequest, PortfolioUploadIntentRequest
from app.services.portfolio_service import PortfolioService


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.refreshes: list[object] = []

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def refresh(self, item: object) -> None:
        self.refreshes.append(item)


class FakePortfolioRepo:
    def __init__(self, item: PortfolioItem | None) -> None:
        self.item = item
        self.lock_calls = 0

    async def get_owned(self, item_id: UUID, user_id: UUID) -> PortfolioItem | None:
        return self._owned(item_id, user_id)

    async def get_owned_for_update(self, item_id: UUID, user_id: UUID) -> PortfolioItem | None:
        self.lock_calls += 1
        return self._owned(item_id, user_id)

    def _owned(self, item_id: UUID, user_id: UUID) -> PortfolioItem | None:
        if (
            self.item is None
            or self.item.id != item_id
            or self.item.user_id != user_id
            or self.item.deleted_at is not None
        ):
            return None
        return self.item


def make_item(*, with_document: bool = False) -> PortfolioItem:
    item = PortfolioItem(
        id=uuid4(),
        user_id=uuid4(),
        title="Candidate mobile redesign",
        verification_status="pending",
    )
    if with_document:
        item.original_filename = "case-study.pdf"
        item.object_key = f"staging/portfolio/{item.user_id}/{item.id}/case-study.pdf"
        item.content_type = "application/pdf"
        item.byte_size = 2048
        item.upload_completed_at = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)
    return item


def make_service(item: PortfolioItem | None) -> tuple[PortfolioService, FakeSession]:
    session = FakeSession()
    settings = SimpleNamespace(
        s3_documents_bucket="private-documents",
        s3_document_key_prefix="staging",
        s3_presigned_put_ttl_seconds=300,
    )
    service = PortfolioService(session, settings=settings)
    service._repo = FakePortfolioRepo(item)
    return service, session


def upload_request(filename: str = "replacement.pdf") -> PortfolioUploadIntentRequest:
    return PortfolioUploadIntentRequest(
        original_filename=filename,
        content_type="application/pdf",
        byte_size=4096,
    )


@pytest.mark.asyncio
async def test_upload_complete_and_download_document(monkeypatch: pytest.MonkeyPatch) -> None:
    item = make_item()
    service, session = make_service(item)

    async def fake_put(**_kwargs) -> str:  # noqa: ANN003
        return "https://private-upload.example.test/signed-put"

    async def fake_get(**_kwargs) -> str:  # noqa: ANN003
        return "https://private-download.example.test/signed-get"

    monkeypatch.setattr("app.services.portfolio_service.generate_presigned_put_url", fake_put)
    monkeypatch.setattr("app.services.portfolio_service.generate_presigned_get_url", fake_get)

    intent = await service.create_upload_intent(item.user_id, item.id, upload_request())
    assert intent.upload_url == "https://private-upload.example.test/signed-put"
    assert intent.headers_required == {"Content-Type": "application/pdf"}
    assert item.upload_completed_at is None

    completed = await service.complete_upload(item.user_id, item.id, SimpleNamespace())
    download = await service.get_download_url(item.user_id, item.id)

    assert completed.upload_completed_at is not None
    assert download.download_url == "https://private-download.example.test/signed-get"
    assert session.commits == 2


@pytest.mark.asyncio
async def test_upload_intent_route_uses_real_single_url_presign_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = make_item()
    service, _ = make_service(item)

    class FakeS3Client:
        def generate_presigned_url(
            self,
            operation: str,
            *,
            Params: dict[str, str],  # noqa: N803
            ExpiresIn: int,  # noqa: N803
        ) -> str:
            assert operation == "put_object"
            assert Params["ContentType"] == "application/pdf"
            assert ExpiresIn == 300
            return "https://private-upload.example.test/real-helper-signed-put"

    monkeypatch.setattr(
        "app.infrastructure.s3.presign.get_s3_client",
        lambda _settings: FakeS3Client(),
    )

    async def override_current_user() -> CurrentUser:
        return CurrentUser(id=item.user_id, email="portfolio-qa@kairo.test", role="candidate")

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_portfolio_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/portfolio/{item.id}/upload-intent",
                json={
                    "original_filename": "replacement.pdf",
                    "content_type": "application/pdf",
                    "byte_size": 4096,
                },
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_portfolio_service, None)

    assert response.status_code == 201
    body = response.json()
    assert body["upload_url"] == "https://private-upload.example.test/real-helper-signed-put"
    assert body["headers_required"] == {"Content-Type": "application/pdf"}


@pytest.mark.asyncio
async def test_replacement_marks_only_new_attachment_as_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = make_item(with_document=True)
    old_key = item.object_key
    service, session = make_service(item)

    async def fake_put(**_kwargs) -> str:  # noqa: ANN003
        return "https://private-upload.example.test/signed-put"

    monkeypatch.setattr("app.services.portfolio_service.generate_presigned_put_url", fake_put)

    await service.create_upload_intent(item.user_id, item.id, upload_request("new-case-study.pdf"))
    assert item.object_key != old_key
    assert item.object_key is not None and item.object_key.endswith("/new-case-study.pdf")
    assert item.original_filename == "new-case-study.pdf"
    assert item.upload_completed_at is None

    await service.complete_upload(item.user_id, item.id, SimpleNamespace())
    assert item.upload_completed_at is not None
    assert session.commits == 2


@pytest.mark.asyncio
async def test_detach_clears_only_current_metadata_without_s3_delete() -> None:
    item = make_item(with_document=True)
    service, session = make_service(item)

    result = await service.detach_document(item.user_id, item.id)

    assert result.title == "Candidate mobile redesign"
    assert result.object_key is None
    assert result.original_filename is None
    assert result.content_type is None
    assert result.byte_size is None
    assert result.upload_completed_at is None
    assert session.commits == 1
    assert "delete" not in PortfolioService.detach_document.__code__.co_names


@pytest.mark.asyncio
async def test_detach_without_document_is_idempotent() -> None:
    item = make_item()
    service, session = make_service(item)

    result = await service.detach_document(item.user_id, item.id)

    assert result is item
    assert session.commits == 0


@pytest.mark.asyncio
async def test_cross_user_and_missing_document_detach_fail_closed() -> None:
    item = make_item(with_document=True)
    service, session = make_service(item)

    with pytest.raises(NotFoundError):
        await service.detach_document(uuid4(), item.id)
    missing_service, _ = make_service(None)
    with pytest.raises(NotFoundError):
        await missing_service.detach_document(item.user_id, item.id)
    assert session.commits == 0


@pytest.mark.asyncio
async def test_metadata_patch_preserves_current_document() -> None:
    item = make_item(with_document=True)
    attachment = (
        item.object_key,
        item.original_filename,
        item.content_type,
        item.byte_size,
        item.upload_completed_at,
    )
    service, _ = make_service(item)

    await service.update(
        item.user_id,
        item.id,
        PortfolioItemUpdateRequest(title="Updated candidate mobile redesign"),
    )

    assert item.title == "Updated candidate mobile redesign"
    assert (
        item.object_key,
        item.original_filename,
        item.content_type,
        item.byte_size,
        item.upload_completed_at,
    ) == attachment


@pytest.mark.asyncio
async def test_document_route_requires_authentication() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(f"/api/v1/portfolio/{uuid4()}/document")
    assert response.status_code == 401


def test_document_route_and_private_response_contract() -> None:
    openapi = app.openapi()
    route = openapi["paths"]["/api/v1/portfolio/{item_id}/document"]["delete"]
    response_schema = openapi["components"]["schemas"]["PortfolioItemResponse"]["properties"]

    assert route["responses"]["200"]
    assert "object_key" not in response_schema
