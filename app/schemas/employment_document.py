"""Employment evidence HTTP DTOs — canonical models live in `app.schemas.employment`."""

from __future__ import annotations

from app.schemas.employment.requests import CompleteUploadRequest, UploadDocumentRequest
from app.schemas.employment.responses import (
    DocumentUploadCompleteResponse,
    DocumentUploadIntentResponse,
    DocumentUploadOptionsResponse,
    EmploymentDocumentResponse,
    ExtractionQueuedAck,
)

DocumentUploadIntentRequest = UploadDocumentRequest
DocumentCompleteUploadRequest = CompleteUploadRequest
EmploymentDocumentPublic = EmploymentDocumentResponse

__all__ = [
    "DocumentCompleteUploadRequest",
    "DocumentUploadCompleteResponse",
    "DocumentUploadIntentRequest",
    "DocumentUploadIntentResponse",
    "DocumentUploadOptionsResponse",
    "EmploymentDocumentPublic",
    "ExtractionQueuedAck",
]
