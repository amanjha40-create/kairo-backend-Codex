"""Education merge and safe DigiLocker evidence preview contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from test_digilocker_lifecycle import harness as digilocker_harness  # noqa: F401

from app.db.session import async_session_factory
from app.exceptions import ConflictError, NotFoundError
from app.main import app
from app.models import Education, EducationDocument, VerificationRequest
from app.services.education_merge_service import EducationMergeService
from app.services.education_service import EducationService
from app.verification_requests.enums import VerificationRequestStatus, VerificationRequestType


@pytest.fixture(name="harness")
async def harness_fixture(digilocker_harness):  # noqa: F811
    await digilocker_harness.activate()
    yield digilocker_harness
    async with async_session_factory() as session:
        await session.execute(
            delete(VerificationRequest).where(
                VerificationRequest.requested_by_user_id.in_(digilocker_harness.ids)
            )
        )
        await session.commit()


async def seed_evidence(
    user_id,
    *,
    degree="Class X",
    institution="Synthetic Secondary School",
    mime="application/xml",
    with_preview=True,
):
    async with async_session_factory() as session:
        education = Education(
            id=uuid4(),
            user_id=user_id,
            institution_name=institution,
            degree=degree,
            education_level="high_school",
            end_date=date(2020, 12, 31),
            end_date_precision="year",
            is_currently_studying=False,
            verification_status="verified",
            verified_at=datetime(2026, 10, 29, tzinfo=UTC),
        )
        metadata = {
            "source": "digilocker",
            "doctype": "SPCER",
            "issuer_name": "Synthetic Board",
            "reference_fingerprint": "a" * 64,
        }
        if with_preview:
            metadata["safe_preview"] = {
                "qualification": "Class X",
                "completion_year": 2020,
            }
        document = EducationDocument(
            id=uuid4(),
            education_id=education.id,
            uploaded_by_user_id=user_id,
            document_type="passing_certificate",
            object_key=f"qa/education/{uuid4()}",
            original_filename="digilocker-spcer.xml" if "xml" in mime else "digilocker-spcer.pdf",
            content_type=mime,
            byte_size=128,
            checksum_sha256="b" * 64,
            verification_status="verified",
            verified_at=datetime(2026, 10, 29, tzinfo=UTC),
            extracted_payload={"digilocker": metadata},
        )
        session.add_all([education, document])
        await session.commit()
        return education.id, document.id


async def test_education_response_exposes_safe_evidence_metadata_only(harness):
    education_id, document_id = await seed_evidence(harness.ids[0])
    async with async_session_factory() as session:
        service = EducationService(session, harness.config)
        response = await service.response(await service.get_owned(harness.ids[0], education_id))
    assert len(response.evidence) == 1
    assert response.evidence[0].model_dump() == {
        "evidence_id": document_id,
        "document_type": "passing_certificate",
        "display_name": "Passing certificate",
        "source": "digilocker",
        "verification_status": "verified",
        "verified_at": datetime(2026, 10, 29, tzinfo=UTC),
        "preview_available": True,
        "preview_type": "structured",
        "content_type": None,
    }
    output = response.model_dump_json()
    assert "reference_fingerprint" not in output
    assert "object_key" not in output
    assert "xml" not in output.casefold()


async def test_xml_evidence_returns_structured_preview_without_raw_content(harness):
    education_id, document_id = await seed_evidence(harness.ids[0], with_preview=False)
    async with async_session_factory() as session:
        result = await EducationService(session, harness.config).get_evidence_preview(
            harness.ids[0], education_id, document_id
        )
    assert result.preview_type == "structured"
    assert result.preview_url is None and result.expires_in_seconds is None
    assert result.structured is not None
    assert result.structured.qualification == "Class X"
    assert result.structured.completion_year == 2020
    output = result.model_dump_json()
    for forbidden in ("reference_fingerprint", "object_key", "uri", "token", "<Certificate"):
        assert forbidden not in output


@pytest.mark.parametrize("mime,preview_type", [("application/pdf", "pdf"), ("image/png", "image")])
async def test_binary_evidence_returns_short_lived_preview(
    harness, monkeypatch, mime, preview_type
):
    education_id, document_id = await seed_evidence(harness.ids[0], mime=mime)
    inspect = AsyncMock(return_value=SimpleNamespace(size=128, content_type=mime))
    presign = AsyncMock(return_value="https://signed.example.invalid/temporary")
    monkeypatch.setattr("app.services.education_service.DocumentPackStorage.inspect", inspect)
    monkeypatch.setattr("app.services.education_service.generate_presigned_get_url", presign)
    async with async_session_factory() as session:
        result = await EducationService(session, harness.config).get_evidence_preview(
            harness.ids[0], education_id, document_id
        )
    assert result.preview_type == preview_type
    assert result.preview_url == "https://signed.example.invalid/temporary"
    assert result.expires_in_seconds == 300
    assert result.structured is None
    assert presign.await_args.kwargs["ttl_seconds"] == 300


async def test_preview_requires_exact_owner_and_parent_binding(harness):
    education_id, document_id = await seed_evidence(harness.ids[0])
    async with async_session_factory() as session:
        service = EducationService(session, harness.config)
        with pytest.raises(NotFoundError):
            await service.get_evidence_preview(harness.ids[1], education_id, document_id)
        other = Education(
            id=uuid4(),
            user_id=harness.ids[0],
            institution_name="Other",
            degree="Class XII",
            education_level="high_school",
            is_currently_studying=False,
            verification_status="draft",
        )
        session.add(other)
        await session.commit()
        with pytest.raises(NotFoundError):
            await service.get_evidence_preview(harness.ids[0], other.id, document_id)


async def test_non_digilocker_document_is_not_exposed_as_evidence(harness):
    education_id, document_id = await seed_evidence(harness.ids[0])
    async with async_session_factory() as session:
        document = await session.get(EducationDocument, document_id)
        document.extracted_payload = {"source": "manual"}
        await session.commit()
        service = EducationService(session, harness.config)
        response = await service.response(await service.get_owned(harness.ids[0], education_id))
        assert response.evidence == []
        with pytest.raises(NotFoundError):
            await service.get_evidence_preview(harness.ids[0], education_id, document_id)


async def test_missing_binary_evidence_fails_closed_without_persistent_copy(harness, monkeypatch):
    education_id, document_id = await seed_evidence(harness.ids[0], mime="application/pdf")
    monkeypatch.setattr(
        "app.services.education_service.DocumentPackStorage.inspect",
        AsyncMock(side_effect=NotFoundError("Selected document is unavailable")),
    )
    async with async_session_factory() as session:
        service = EducationService(session, harness.config)
        with pytest.raises(NotFoundError):
            await service.get_evidence_preview(harness.ids[0], education_id, document_id)
        with pytest.raises(NotFoundError):
            await service.get_evidence_preview(harness.ids[0], education_id, document_id)
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EducationDocument)
                .where(EducationDocument.education_id == education_id)
            )
            == 1
        )


async def test_clear_match_merge_preserves_canonical_record_and_rehomes_history(harness):
    canonical_id, _ = await seed_evidence(
        harness.ids[0], institution="Synthetic Secondary School"
    )
    async with async_session_factory() as session:
        canonical = await session.get(Education, canonical_id)
        canonical.verification_status = "draft"
        canonical.verified_at = None
        existing_document = await session.scalar(
            select(EducationDocument).where(EducationDocument.education_id == canonical_id)
        )
        existing_document.deleted_at = datetime.now(tz=UTC)
        duplicate = Education(
            id=uuid4(),
            user_id=harness.ids[0],
            institution_name="Maharashtra State Board of Secondary and Higher Secondary Education",
            degree="Class X",
            education_level="high_school",
            end_date=date(2020, 12, 31),
            end_date_precision="year",
            is_currently_studying=False,
            verification_status="verified",
            verified_at=datetime(2026, 10, 29, tzinfo=UTC),
        )
        document = EducationDocument(
            id=uuid4(),
            education_id=duplicate.id,
            uploaded_by_user_id=harness.ids[0],
            document_type="passing_certificate",
            object_key=f"qa/education/{uuid4()}",
            original_filename="digilocker-spcer.pdf",
            content_type="application/pdf",
            byte_size=128,
            checksum_sha256="c" * 64,
            verification_status="verified",
            verified_at=datetime(2026, 10, 29, tzinfo=UTC),
            extracted_payload={
                "digilocker": {
                    "source": "digilocker",
                    "reference_fingerprint": "d" * 64,
                }
            },
        )
        request = VerificationRequest(
            id=uuid4(),
            requested_by_user_id=harness.ids[0],
            subject_user_id=harness.ids[0],
            subject_name="Synthetic",
            subject_email="synthetic@example.test",
            request_type=VerificationRequestType.EDUCATION,
            status=VerificationRequestStatus.DRAFT,
            education_id=duplicate.id,
        )
        session.add_all([duplicate, document, request])
        await session.commit()
        result = await EducationMergeService(session).merge_digilocker_duplicate(
            user_id=harness.ids[0], canonical_id=canonical.id, duplicate_id=duplicate.id
        )
        await session.refresh(canonical)
        await session.refresh(duplicate)
        await session.refresh(document)
        await session.refresh(request)
    assert result.match_result == "CLEAR_MATCH"
    assert result.evidence_moved == result.verification_requests_moved == 1
    assert canonical.deleted_at is None and canonical.verification_status == "verified"
    assert duplicate.deleted_at is not None
    assert document.education_id == request.education_id == canonical.id


async def test_nonmatching_merge_aborts_without_partial_mutation(harness):
    canonical_id, _ = await seed_evidence(harness.ids[0])
    duplicate_id, document_id = await seed_evidence(
        harness.ids[0], degree="Class XII", institution="Synthetic Higher Secondary School"
    )
    async with async_session_factory() as session:
        with pytest.raises(ConflictError):
            await EducationMergeService(session).merge_digilocker_duplicate(
                user_id=harness.ids[0], canonical_id=canonical_id, duplicate_id=duplicate_id
            )
        await session.rollback()
        duplicate = await session.get(Education, duplicate_id)
        document = await session.get(EducationDocument, document_id)
    assert duplicate.deleted_at is None
    assert document.education_id == duplicate_id


def test_preview_route_requires_auth_and_exposes_only_safe_contract():
    route = app.openapi()["paths"][
        "/api/v1/educations/{education_id}/evidence/{evidence_id}/preview"
    ]["get"]
    assert route["security"]
    schema = app.openapi()["components"]["schemas"]["EducationEvidencePreviewResponse"]
    serialized = str(schema).casefold()
    for forbidden in ("object_key", "bucket", "digilocker_uri", "raw_xml", "token"):
        assert forbidden not in serialized
