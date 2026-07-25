import pytest
from pydantic import ValidationError

from app.schemas.user_document import UserDocumentUploadIntentRequest


def test_user_document_upload_accepts_supported_private_formats() -> None:
    payload = UserDocumentUploadIntentRequest(
        document_type="government_id",
        original_filename="identity.pdf",
        content_type="APPLICATION/PDF",
        byte_size=1024,
    )
    assert payload.content_type == "application/pdf"


@pytest.mark.parametrize(
    ("filename", "content_type", "byte_size"),
    [
        ("../identity.pdf", "application/pdf", 1024),
        ("identity.exe", "application/x-msdownload", 1024),
        ("identity.pdf", "application/pdf", 50 * 1024 * 1024 + 1),
    ],
)
def test_user_document_upload_rejects_unsafe_or_oversized_files(
    filename: str, content_type: str, byte_size: int,
) -> None:
    with pytest.raises(ValidationError):
        UserDocumentUploadIntentRequest(
            document_type="government_id",
            original_filename=filename,
            content_type=content_type,
            byte_size=byte_size,
        )
