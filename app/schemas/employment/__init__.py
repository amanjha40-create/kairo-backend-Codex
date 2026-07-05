"""Employment verification HTTP schemas — requests, responses, filters, pagination aliases."""

from __future__ import annotations

from app.schemas.employment.filters import AdminEmploymentListFilters, EmploymentListFilters
from app.schemas.employment.requests import (
    AddRemarkRequest,
    AdminDecisionSummaryBody,
    AdminDocumentDecisionBody,
    AdminDocumentRejectBody,
    AdminRejectRequest,
    AdminVerificationRequest,
    AdminVerifyRequest,
    AssignReviewRequest,
    CompleteUploadRequest,
    CreateEmploymentRequest,
    DocumentConfirmUploadRequest,
    DocumentPresignedUrlRequest,
    UpdateEmploymentRequest,
    UploadDocumentRequest,
)
from app.schemas.employment.responses import (
    AllowedContentTypeOption,
    AuditEventListResponse,
    AuditEventResponse,
    DocumentTypeOption,
    DocumentUploadCompleteResponse,
    DocumentUploadIntentResponse,
    DocumentUploadOptionsResponse,
    EmploymentCancelResponse,
    EmploymentDocumentListResponse,
    EmploymentDocumentResponse,
    EmploymentListResponse,
    EmploymentResponse,
    EmploymentSubmitResponse,
    ExtractionQueuedAck,
    VerificationResponse,
)

# --- Backward-compatible names (pre-package refactor) ---

EmploymentCreate = CreateEmploymentRequest
EmploymentUpdate = UpdateEmploymentRequest
EmploymentPublic = EmploymentResponse
EmploymentDetail = VerificationResponse
AdminVerificationTransitionRequest = AdminVerificationRequest

__all__ = [
    "AddRemarkRequest",
    "AdminDecisionSummaryBody",
    "AdminDocumentDecisionBody",
    "AdminDocumentRejectBody",
    "AdminEmploymentListFilters",
    "AdminRejectRequest",
    "AdminVerificationRequest",
    "AdminVerificationTransitionRequest",
    "AdminVerifyRequest",
    "AllowedContentTypeOption",
    "AuditEventListResponse",
    "AuditEventResponse",
    "AssignReviewRequest",
    "CompleteUploadRequest",
    "CreateEmploymentRequest",
    "DocumentConfirmUploadRequest",
    "DocumentPresignedUrlRequest",
    "DocumentTypeOption",
    "DocumentUploadCompleteResponse",
    "DocumentUploadIntentResponse",
    "DocumentUploadOptionsResponse",
    "EmploymentCancelResponse",
    "EmploymentCreate",
    "EmploymentDetail",
    "EmploymentDocumentListResponse",
    "EmploymentDocumentResponse",
    "EmploymentListFilters",
    "EmploymentListResponse",
    "EmploymentPublic",
    "EmploymentResponse",
    "EmploymentSubmitResponse",
    "EmploymentUpdate",
    "ExtractionQueuedAck",
    "UpdateEmploymentRequest",
    "UploadDocumentRequest",
    "VerificationResponse",
]
