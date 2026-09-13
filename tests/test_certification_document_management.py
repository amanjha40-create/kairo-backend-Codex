from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.main import app
from app.models.certification import Certification
from app.schemas.certification import (
    CertificationDocumentCompleteUploadRequest,
    CertificationDocumentUploadIntentRequest,
    CertificationUpdateRequest,
)
from app.services.certification_service import CertificationService

CHECKSUM_A = "a" * 64
CHECKSUM_B = "b" * 64


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


class FakeCertificationRepo:
    def __init__(self, item: Certification | None) -> None:
        self.item = item
        self.lock_calls = 0

    async def get_owned(self, item_id: UUID, user_id: UUID) -> Certification | None:
        return self._owned(item_id, user_id)

    async def get_owned_for_update(self, item_id: UUID, user_id: UUID) -> Certification | None:
        self.lock_calls += 1
        return self._owned(item_id, user_id)

    def _owned(self, item_id: UUID, user_id: UUID) -> Certification | None:
        if (
            self.item is None
            or self.item.id != item_id
            or self.item.user_id != user_id
            or self.item.deleted_at is not None
        ):
            return None
        return self.item


def make_service(item: Certification | None) -> tuple[CertificationService, FakeSession]:
    session = FakeSession()
    settings = SimpleNamespace(
        s3_documents_bucket="private-documents",
        s3_document_key_prefix="staging",
        jwt_secret_key="test-certification-document-secret",
        jwt_algorithm="HS256",
    )
    service = CertificationService(session, settings=settings)
    service._repo = FakeCertificationRepo(item)
    return service, session


def make_certification(*, with_document: bool = False) -> Certification:
    item = Certification(
        id=uuid4(),
        user_id=uuid4(),
        title="Cloud Architecture",
        issuing_organization="KairoID QA",
        issued_date=date(2025, 1, 1),
        verification_status=Certification.SELF_DECLARED_STATUS,
    )
    if with_document:
        item.object_key = "staging/certifications/owner/cert/old/certificate.pdf"
        item.original_filename = "certificate.pdf"
        item.content_type = "application/pdf"
        item.byte_size = 128
        item.checksum_sha256 = CHECKSUM_A
    return item


def upload_request(
    *,
    filename: str = "updated-certificate.pdf",
    checksum: str = CHECKSUM_B,
) -> CertificationDocumentUploadIntentRequest:
    return CertificationDocumentUploadIntentRequest(
        original_filename=filename,
        content_type="application/pdf",
        byte_size=256,
        checksum_sha256=checksum,
    )


async def issue_intent(
    service: CertificationService,
    item: Certification,
    monkeypatch: pytest.MonkeyPatch,
    *,
    payload: CertificationDocumentUploadIntentRequest | None = None,
) -> tuple[str, str]:
    captured: dict[str, object] = {}

    async def fake_put_url(**kwargs) -> str:  # noqa: ANN003
        captured.update(kwargs)
        return "https://private-upload.example.test/signed-put"

    monkeypatch.setattr(
        "app.services.certification_service.generate_presigned_put_url",
        fake_put_url,
    )
    response = await service.create_document_upload_intent(
        item.user_id,
        item.id,
        payload or upload_request(),
    )
    assert response.upload_url.startswith("https://private-upload.example.test/")
    assert "object_key" not in response.model_dump()
    return response.upload_token, str(captured["object_key"])


def stub_uploaded_object(
    monkeypatch: pytest.MonkeyPatch,
    *,
    byte_size: int = 256,
    content_type: str = "application/pdf",
) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    async def fake_head(**kwargs) -> dict[str, object]:  # noqa: ANN003
        calls.append(kwargs)
        return {"ContentLength": byte_size, "ContentType": content_type}

    monkeypatch.setattr("app.services.certification_service.head_object_meta", fake_head)
    return calls


@pytest.mark.asyncio
async def test_document_can_be_added_after_certification_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = make_certification()
    service, session = make_service(item)
    token, expected_key = await issue_intent(service, item, monkeypatch)
    stub_uploaded_object(monkeypatch)

    result = await service.complete_document_upload(
        item.user_id,
        item.id,
        CertificationDocumentCompleteUploadRequest(
            upload_token=token,
            checksum_sha256=CHECKSUM_B,
        ),
    )

    assert result.object_key == expected_key
    assert result.original_filename == "updated-certificate.pdf"
    assert result.content_type == "application/pdf"
    assert result.byte_size == 256
    assert result.checksum_sha256 == CHECKSUM_B
    assert session.commits == 1


@pytest.mark.asyncio
async def test_completed_document_can_be_downloaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = make_certification(with_document=True)
    service, _ = make_service(item)

    async def fake_download(**_kwargs) -> str:  # noqa: ANN003
        return "https://private-download.example.test/signed-get"

    monkeypatch.setattr(
        "app.services.certification_service.generate_presigned_get_url",
        fake_download,
    )

    response = await service.get_download_url(item.user_id, item.id)

    assert response.download_url == "https://private-download.example.test/signed-get"


@pytest.mark.asyncio
async def test_replacement_atomically_unlinks_the_previous_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = make_certification(with_document=True)
    previous_key = item.object_key
    service, session = make_service(item)
    token, replacement_key = await issue_intent(service, item, monkeypatch)
    stub_uploaded_object(monkeypatch)

    result = await service.complete_document_upload(
        item.user_id,
        item.id,
        CertificationDocumentCompleteUploadRequest(
            upload_token=token,
            checksum_sha256=CHECKSUM_B,
        ),
    )

    assert result.object_key == replacement_key
    assert result.object_key != previous_key
    assert result.checksum_sha256 == CHECKSUM_B
    assert session.commits == 1


@pytest.mark.asyncio
async def test_repeated_completion_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = make_certification()
    service, session = make_service(item)
    token, _ = await issue_intent(service, item, monkeypatch)
    head_calls = stub_uploaded_object(monkeypatch)
    payload = CertificationDocumentCompleteUploadRequest(
        upload_token=token,
        checksum_sha256=CHECKSUM_B,
    )

    first = await service.complete_document_upload(item.user_id, item.id, payload)
    second = await service.complete_document_upload(item.user_id, item.id, payload)

    assert second is first
    assert session.commits == 1
    assert len(head_calls) == 1


@pytest.mark.asyncio
async def test_stale_completion_cannot_overwrite_a_newer_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = make_certification(with_document=True)
    service, _ = make_service(item)
    older_token, _ = await issue_intent(
        service,
        item,
        monkeypatch,
        payload=upload_request(filename="older.pdf", checksum=CHECKSUM_A),
    )
    newer_token, newer_key = await issue_intent(service, item, monkeypatch)
    stub_uploaded_object(monkeypatch)

    await service.complete_document_upload(
        item.user_id,
        item.id,
        CertificationDocumentCompleteUploadRequest(
            upload_token=newer_token,
            checksum_sha256=CHECKSUM_B,
        ),
    )
    with pytest.raises(ConflictError):
        await service.complete_document_upload(
            item.user_id,
            item.id,
            CertificationDocumentCompleteUploadRequest(
                upload_token=older_token,
                checksum_sha256=CHECKSUM_A,
            ),
        )

    assert item.object_key == newer_key
    assert item.checksum_sha256 == CHECKSUM_B


@pytest.mark.asyncio
async def test_detach_clears_linkage_without_deleting_storage() -> None:
    item = make_certification(with_document=True)
    service, session = make_service(item)

    result = await service.detach_document(item.user_id, item.id)

    assert result.object_key is None
    assert result.original_filename is None
    assert result.content_type is None
    assert result.byte_size is None
    assert result.checksum_sha256 is None
    assert session.commits == 1
    assert "delete" not in CertificationService.detach_document.__code__.co_names


@pytest.mark.asyncio
async def test_detach_is_deterministic_when_no_document_exists() -> None:
    item = make_certification()
    service, session = make_service(item)

    result = await service.detach_document(item.user_id, item.id)

    assert result is item
    assert session.commits == 0


@pytest.mark.asyncio
async def test_metadata_patch_preserves_attachment_fields() -> None:
    item = make_certification(with_document=True)
    attachment = (
        item.object_key,
        item.original_filename,
        item.content_type,
        item.byte_size,
        item.checksum_sha256,
    )
    service, _ = make_service(item)

    await service.update(
        item.user_id,
        item.id,
        CertificationUpdateRequest(title="Updated Cloud Architecture"),
    )

    assert item.title == "Updated Cloud Architecture"
    assert (
        item.object_key,
        item.original_filename,
        item.content_type,
        item.byte_size,
        item.checksum_sha256,
    ) == attachment


@pytest.mark.asyncio
async def test_cross_user_document_operations_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = make_certification()
    service, _ = make_service(item)
    intruder_id = uuid4()
    with pytest.raises(NotFoundError):
        await service.create_document_upload_intent(
            intruder_id,
            item.id,
            upload_request(),
        )

    token, _ = await issue_intent(service, item, monkeypatch)
    with pytest.raises(ForbiddenError):
        await service.complete_document_upload(
            intruder_id,
            item.id,
            CertificationDocumentCompleteUploadRequest(
                upload_token=token,
                checksum_sha256=CHECKSUM_B,
            ),
        )
    with pytest.raises(NotFoundError):
        await service.detach_document(intruder_id, item.id)


@pytest.mark.asyncio
async def test_missing_and_soft_deleted_certifications_are_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_service, _ = make_service(None)
    with pytest.raises(NotFoundError):
        await missing_service.create_document_upload_intent(
            uuid4(),
            uuid4(),
            upload_request(),
        )

    deleted = make_certification()
    deleted.deleted_at = date.today()
    deleted_service, _ = make_service(deleted)
    with pytest.raises(NotFoundError):
        await deleted_service.detach_document(deleted.user_id, deleted.id)


@pytest.mark.asyncio
async def test_checksum_and_uploaded_object_mismatches_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = make_certification()
    service, session = make_service(item)
    token, _ = await issue_intent(service, item, monkeypatch)

    with pytest.raises(ValidationAppError, match="checksum"):
        await service.complete_document_upload(
            item.user_id,
            item.id,
            CertificationDocumentCompleteUploadRequest(
                upload_token=token,
                checksum_sha256=CHECKSUM_A,
            ),
        )

    stub_uploaded_object(monkeypatch, byte_size=255)
    with pytest.raises(ValidationAppError, match="size"):
        await service.complete_document_upload(
            item.user_id,
            item.id,
            CertificationDocumentCompleteUploadRequest(
                upload_token=token,
                checksum_sha256=CHECKSUM_B,
            ),
        )
    assert session.commits == 0


def test_document_management_routes_and_private_response_contract() -> None:
    openapi = app.openapi()
    paths = openapi["paths"]

    assert "post" in paths["/api/v1/certifications/{certification_id}/document/upload-intent"]
    assert "post" in paths["/api/v1/certifications/{certification_id}/document/complete-upload"]
    assert "delete" in paths["/api/v1/certifications/{certification_id}/document"]
    assert "get" in paths["/api/v1/certifications/{certification_id}/download-url"]

    intent_schema = openapi["components"]["schemas"][
        "CertificationDocumentUploadIntentResponse"
    ]["properties"]
    certification_schema = openapi["components"]["schemas"]["CertificationResponse"][
        "properties"
    ]
    assert "object_key" not in intent_schema
    assert "object_key" not in certification_schema
    assert "upload_url" in intent_schema
    assert "upload_token" in intent_schema
