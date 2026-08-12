from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.certification import Certification
from app.schemas.certification import (
    CertificationCreateRequest,
    CertificationResponse,
    CertificationUpdateRequest,
    CertificationUploadIntentRequest,
)
from app.services.certification_service import CertificationService
from app.services.resume_review_service import ResumeReviewService


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.refreshes: list[object] = []
        self.flushes = 0

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, item: object) -> None:
        self.refreshes.append(item)


class FakeCertificationRepo:
    def __init__(self, item: Certification | None = None) -> None:
        self.item = item
        self.deleted: Certification | None = None

    async def create(self, item: Certification) -> Certification:
        self.item = item
        return item

    async def get_owned(self, _item_id, _user_id) -> Certification | None:  # noqa: ANN001
        return self.item

    async def soft_delete(self, item: Certification) -> None:
        item.deleted_at = datetime.now(tz=UTC)
        self.deleted = item


@pytest.mark.asyncio
async def test_manual_certification_create_defaults_to_self_declared() -> None:
    session = FakeSession()
    service = CertificationService(session, settings=SimpleNamespace())

    item = await service.create(
        uuid4(),
        CertificationCreateRequest(
            title="Career QA Product Management Certificate",
            issuing_organization="Kairo QA Institute",
            issued_date=date(2025, 1, 1),
        ),
    )

    assert item.verification_status == Certification.SELF_DECLARED_STATUS
    assert session.added == [item]
    assert session.commits == 1
    assert all(obj.__class__.__name__ != "VerificationRequest" for obj in session.added)


@pytest.mark.asyncio
async def test_certification_upload_intent_defaults_to_self_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    service = CertificationService(
        session,
        settings=SimpleNamespace(
            s3_documents_bucket="kairo-documents",
            s3_document_key_prefix="staging",
        ),
    )

    async def fake_put_url(**_kwargs) -> str:
        return "https://uploads.example.com/put"

    monkeypatch.setattr(
        "app.services.certification_service.generate_presigned_put_url",
        fake_put_url,
    )

    response = await service.create_upload_intent(
        uuid4(),
        CertificationUploadIntentRequest(
            title="Career QA Product Management Certificate",
            issuing_organization="Kairo QA Institute",
            issued_date=None,
            expiry_date=None,
            does_not_expire=True,
            credential_id=None,
            credential_url=None,
            original_filename="certificate.pdf",
            content_type="application/pdf",
            byte_size=128,
        ),
    )

    created = session.added[0]
    assert isinstance(created, Certification)
    assert created.verification_status == Certification.SELF_DECLARED_STATUS
    assert response.object_key == created.object_key
    assert session.commits == 1
    assert all(obj.__class__.__name__ != "VerificationRequest" for obj in session.added)


@pytest.mark.asyncio
async def test_editing_certification_preserves_self_declared_status() -> None:
    session = FakeSession()
    existing = Certification(
        id=uuid4(),
        user_id=uuid4(),
        title="Career QA Product Management Certificate",
        issuing_organization="Kairo QA Institute",
        issued_date=date(2025, 1, 1),
        verification_status=Certification.SELF_DECLARED_STATUS,
    )
    repo = FakeCertificationRepo(existing)
    service = CertificationService(session, settings=SimpleNamespace())
    service._repo = repo

    updated = await service.update(
        existing.user_id,
        existing.id,
        CertificationUpdateRequest(title="Updated Certificate Title"),
    )

    assert updated.title == "Updated Certificate Title"
    assert updated.verification_status == Certification.SELF_DECLARED_STATUS
    assert session.commits == 1


@pytest.mark.asyncio
async def test_delete_certification_preserves_existing_contract() -> None:
    session = FakeSession()
    existing = Certification(
        id=uuid4(),
        user_id=uuid4(),
        title="Career QA Product Management Certificate",
        issuing_organization="Kairo QA Institute",
        issued_date=date(2025, 1, 1),
        verification_status=Certification.SELF_DECLARED_STATUS,
    )
    repo = FakeCertificationRepo(existing)
    service = CertificationService(session, settings=SimpleNamespace())
    service._repo = repo

    await service.delete(existing.user_id, existing.id)

    assert repo.deleted is existing
    assert existing.deleted_at is not None
    assert existing.verification_status == Certification.SELF_DECLARED_STATUS
    assert session.commits == 1


@pytest.mark.asyncio
async def test_resume_imported_certification_is_self_declared() -> None:
    service = ResumeReviewService(SimpleNamespace())

    record = await service._create_record(
        uuid4(),
        "certification",
        {
            "title": "Career QA Product Management Certificate",
            "issuing_organization": "Kairo QA Institute",
            "issued_date": None,
            "expiry_date": None,
            "credential_id": None,
            "credential_url": None,
        },
    )

    assert record.verification_status == Certification.SELF_DECLARED_STATUS


def test_certification_response_preserves_stored_pending_status_for_historical_rows() -> None:
    row = Certification(
        id=uuid4(),
        user_id=uuid4(),
        title="Legacy Pending Certification",
        issuing_organization="Legacy Org",
        issued_date=date(2025, 1, 1),
        verification_status="pending",
    )

    response = CertificationResponse.model_validate(row)

    assert response.verification_status == "pending"
