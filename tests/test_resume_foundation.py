from __future__ import annotations

import hashlib
import io
import zipfile
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.resumes.providers import DeterministicDocxExtractor, NovaResumeParser
from app.exceptions import ConflictError, NotFoundError
from app.resumes.enums import ResumeProcessingStatus
from app.resumes.schemas import (
    EmploymentClaim,
    ParsedResumeResult,
    ResumeCompleteUploadRequest,
    ResumeUploadIntentRequest,
)
from app.resumes.validation import validate_resume_bytes, validate_resume_declaration
from app.services.resume_service import ResumeService


def _docx_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr(
            "word/document.xml",
            """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Kairo</w:t></w:r></w:p><w:p><w:r><w:t>Engineer</w:t></w:r></w:p></w:body></w:document>""",
        )
    return output.getvalue()


def test_resume_declaration_and_signatures_are_strict() -> None:
    assert validate_resume_declaration(
        filename="../resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        byte_size=100,
        max_bytes=1000,
    ) == "resume.docx"
    assert validate_resume_bytes(_docx_bytes(), content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", max_bytes=1000) == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    with pytest.raises(Exception):
        validate_resume_bytes(b"not a pdf", content_type="application/pdf", max_bytes=1000)


@pytest.mark.asyncio
async def test_docx_extraction_is_deterministic_and_does_not_call_shell() -> None:
    text = await DeterministicDocxExtractor().extract(_docx_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert text == "Kairo\nEngineer"


def test_parsed_claims_are_candidate_provided_and_unverified() -> None:
    result = ParsedResumeResult(employments=[EmploymentClaim(company_name="Kairo")])
    claim = result.employments[0]
    assert claim.source_type == "resume"
    assert claim.selected_for_import is False
    assert not hasattr(claim, "verified")


def test_checksum_contract_rejects_non_sha256_values() -> None:
    with pytest.raises(ValidationError):
        ResumeCompleteUploadRequest(checksum_sha256="not-a-checksum")


@pytest.mark.asyncio
async def test_resume_upload_intent_is_committed_for_followup_requests() -> None:
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    settings = SimpleNamespace(
        resume_processing_enabled=True,
        resume_max_upload_bytes=10_000_000,
        resume_retention_days=7,
        s3_documents_bucket="synthetic-test-bucket",
    )
    service = ResumeService(session, settings)
    service.storage = SimpleNamespace(
        presign_put_url=AsyncMock(return_value=("https://example.invalid/upload", 300))
    )

    response = await service.create_upload_intent(
        uuid4(),
        ResumeUploadIntentRequest(
            original_filename="synthetic-resume.pdf",
            content_type="application/pdf",
            byte_size=128,
            consent_version="test-v1",
        ),
    )

    assert response.resume_id is not None
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_resume_complete_refreshes_server_fields_before_serializing() -> None:
    content = b"%PDF-1.4 synthetic acceptance fixture"
    now = datetime.now(UTC)
    row = SimpleNamespace(
        id=uuid4(),
        storage_key="resumes/synthetic/resume.pdf",
        file_size_bytes=len(content),
        content_type="application/pdf",
        checksum_sha256=None,
        upload_status="pending_upload",
        processing_status="pending_upload",
        original_filename="resume.pdf",
        created_at=now,
        updated_at=now,
    )
    session = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    settings = SimpleNamespace(resume_max_upload_bytes=10_000_000)
    service = ResumeService(session, settings)
    service.storage = SimpleNamespace(verify_upload_matches_intent=AsyncMock())
    service._owned = AsyncMock(return_value=row)
    service._read_object = AsyncMock(return_value=content)

    response = await service.complete_upload(
        uuid4(),
        row.id,
        ResumeCompleteUploadRequest(checksum_sha256=hashlib.sha256(content).hexdigest()),
    )

    assert response.upload_status == "uploaded"
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(row)


@pytest.mark.asyncio
async def test_resume_process_is_idempotent_after_result_needs_review() -> None:
    resume_id = uuid4()
    job = SimpleNamespace(id=uuid4(), status=ResumeProcessingStatus.NEEDS_REVIEW.value)
    session = MagicMock()
    session.scalar = AsyncMock(return_value=job)
    settings = SimpleNamespace(resume_max_retries=3)
    service = ResumeService(session, settings)
    service._owned = AsyncMock(return_value=SimpleNamespace(upload_status="uploaded"))

    response = await service.process(uuid4(), resume_id)

    assert response.job_id == job.id
    assert response.status == ResumeProcessingStatus.NEEDS_REVIEW.value
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_resume_process_enforces_retry_limit() -> None:
    latest = SimpleNamespace(id=uuid4(), status=ResumeProcessingStatus.FAILED.value)
    session = MagicMock()
    session.scalar = AsyncMock(side_effect=[latest, 4])
    settings = SimpleNamespace(resume_max_retries=3)
    service = ResumeService(session, settings)
    service._owned = AsyncMock(return_value=SimpleNamespace(upload_status="uploaded"))

    with pytest.raises(ConflictError, match="retry limit"):
        await service.process(uuid4(), uuid4())

    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_resume_lookup_hides_unowned_records() -> None:
    session = MagicMock()
    session.scalar = AsyncMock(return_value=None)
    service = ResumeService(session, SimpleNamespace())

    with pytest.raises(NotFoundError, match="Resume not found"):
        await service.get(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_nova_parser_validates_structured_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class Body:
        def read(self) -> bytes:
            return json.dumps({"output": {"message": {"content": [{"text": '{"schema_version":"1"}'}]}}}).encode()

    class Client:
        def invoke_model(self, **kwargs: object) -> dict[str, Body]:
            assert kwargs["modelId"] == "us.amazon.nova-2-lite-v1:0"
            request = json.loads(str(kwargs["body"]))
            system_text = request["system"][0]["text"]
            user_text = request["messages"][0]["content"][0]["text"]
            assert '"candidate_profile"' in system_text
            assert '"employments"' in system_text
            assert "with no wrapper" in system_text
            assert "<resume_data>\nsynthetic resume\n</resume_data>" == user_text
            assert "selected_for_import must be false" in system_text
            return {"body": Body()}

    monkeypatch.setattr("app.resumes.providers.boto3.client", lambda *args, **kwargs: Client())
    settings = SimpleNamespace(aws_region="us-east-1", bedrock_model_id="us.amazon.nova-2-lite-v1:0")
    result = await NovaResumeParser(settings).parse("synthetic resume")
    assert result.schema_version == "1"
