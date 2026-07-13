"""Document upload catalog for clients."""

from __future__ import annotations

from app.config import Settings
from app.employment.document_catalog import build_document_upload_options
from app.employment.enums import EmploymentDocumentType, VerificationMethod


def test_build_document_upload_options_includes_all_types() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost/db",
        jwt_secret_key="test-jwt-secret-key-32-chars-minimum!!",
    )
    options = build_document_upload_options(settings)
    values = {item["value"] for item in options["document_types"]}
    assert values == {t.value for t in EmploymentDocumentType}
    method_values = {item["value"] for item in options["verification_methods"]}
    assert method_values == {m.value for m in VerificationMethod}
    assert options["extraction_enabled"] is False
    assert options["max_upload_bytes"] == settings.employment_max_upload_bytes


def test_document_catalog_includes_canonical_employment_types() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost/db",
        jwt_secret_key="test-jwt-secret-key-32-chars-minimum!!",
    )
    values = {item["value"] for item in build_document_upload_options(settings)["document_types"]}

    assert {
        "appointment_letter",
        "experience_letter",
        "payslip",
        "employment_id_card",
        "contract",
        "bank_statement",
    } <= values
