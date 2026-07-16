from __future__ import annotations

import io
import zipfile
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.resumes.providers import DeterministicDocxExtractor, NovaResumeParser
from app.resumes.schemas import EmploymentClaim, ParsedResumeResult, ResumeCompleteUploadRequest
from app.resumes.validation import validate_resume_bytes, validate_resume_declaration


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
async def test_nova_parser_validates_structured_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class Body:
        def read(self) -> bytes:
            return json.dumps({"output": {"message": {"content": [{"text": '{"schema_version":"1"}'}]}}}).encode()

    class Client:
        def invoke_model(self, **kwargs: object) -> dict[str, Body]:
            assert kwargs["modelId"] == "us.amazon.nova-2-lite-v1:0"
            return {"body": Body()}

    monkeypatch.setattr("app.resumes.providers.boto3.client", lambda *args, **kwargs: Client())
    settings = SimpleNamespace(aws_region="us-east-1", bedrock_model_id="us.amazon.nova-2-lite-v1:0")
    result = await NovaResumeParser(settings).parse("synthetic resume")
    assert result.schema_version == "1"
