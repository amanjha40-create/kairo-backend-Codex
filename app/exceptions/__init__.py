"""Domain-facing exception hierarchy — mapped to HTTP in handlers."""

from __future__ import annotations

from app.exceptions.base import (
    AppException,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationAppError,
)
from app.exceptions.employment_domain import (
    ActiveVerificationPipelineConflictError,
    DocumentExtractionBusyError,
    DuplicateEmploymentDocumentError,
    EmploymentAccessDeniedError,
    EmploymentCaseNotFoundError,
    EmploymentDateValidationError,
    EmploymentWorkflowError,
)

__all__ = [
    "ActiveVerificationPipelineConflictError",
    "AppException",
    "ConflictError",
    "DocumentExtractionBusyError",
    "DuplicateEmploymentDocumentError",
    "EmploymentAccessDeniedError",
    "EmploymentCaseNotFoundError",
    "EmploymentDateValidationError",
    "EmploymentWorkflowError",
    "ForbiddenError",
    "NotFoundError",
    "RateLimitError",
    "ServiceUnavailableError",
    "UnauthorizedError",
    "ValidationAppError",
]
