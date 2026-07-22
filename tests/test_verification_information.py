from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.verification_request import VerificationRequestInformationSubmissionRequest
from app.schemas.user_document import UserDocumentUploadIntentRequest
from app.user_documents.enums import UserDocumentType
from app.verification_requests.enums import VerificationRequestStatus


def test_candidate_information_response_is_trimmed_and_bounded() -> None:
    payload = VerificationRequestInformationSubmissionRequest(response="  The requested detail  ")
    assert payload.response == "The requested detail"


def test_candidate_information_response_cannot_be_empty_or_oversized() -> None:
    with pytest.raises(ValidationError):
        VerificationRequestInformationSubmissionRequest(response="   ")
    with pytest.raises(ValidationError):
        VerificationRequestInformationSubmissionRequest(response="x" * 4001)


def test_document_upload_accepts_a_replacement_reference() -> None:
    document_id = uuid4()
    payload = UserDocumentUploadIntentRequest(
        document_type=UserDocumentType.OTHER,
        original_filename="evidence.pdf",
        content_type="application/pdf",
        byte_size=128,
        replaces_document_id=document_id,
    )
    assert payload.replaces_document_id == document_id


def test_information_requests_are_subject_editable() -> None:
    assert VerificationRequestStatus.AWAITING_INFORMATION.value == "awaiting_information"
