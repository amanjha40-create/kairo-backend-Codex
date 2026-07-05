"""Employment verification domain errors — map to HTTP via existing `AppException` subclasses."""

from __future__ import annotations

from app.exceptions.base import ConflictError, ForbiddenError, NotFoundError, ValidationAppError


class EmploymentCaseNotFoundError(NotFoundError):
    """Active employment case missing or not visible to principal."""

    def __init__(self, message: str = "Employment case not found") -> None:
        super().__init__(message)


class EmploymentAccessDeniedError(ForbiddenError):
    """Ownership or scope prevents access."""

    def __init__(self, message: str = "Access denied for this employment case") -> None:
        super().__init__(message)


class EmploymentWorkflowError(ValidationAppError):
    """Illegal action for current verification status."""

    def __init__(self, message: str, *, code: str = "employment_workflow_error") -> None:
        super().__init__(message, code=code)


class EmploymentDateValidationError(ValidationAppError):
    """Cross-field date rules failed after patch."""

    def __init__(self, message: str = "Invalid employment date range") -> None:
        super().__init__(message, code="employment_date_invalid")


class DuplicateEmploymentDocumentError(ConflictError):
    """Duplicate upload intent or identical finalized digest under the same case."""

    def __init__(self, message: str = "Duplicate document for this employment case") -> None:
        super().__init__(message)


class ActiveVerificationPipelineConflictError(ConflictError):
    """Another case is already in the reviewer pipeline for this principal."""

    def __init__(
        self,
        message: str = "Another verification is already in progress for your account",
    ) -> None:
        super().__init__(message)


class DocumentExtractionBusyError(ConflictError):
    """Serialized extraction pipeline — another document job is active for this case."""

    def __init__(
        self,
        message: str = "Another document is currently being processed for this employment case",
    ) -> None:
        super().__init__(message)
