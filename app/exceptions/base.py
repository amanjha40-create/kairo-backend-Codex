"""Core exception types — separated so domain modules can subclass without import cycles."""

from __future__ import annotations


class AppException(Exception):
    """Base application error with stable machine code for API clients."""

    def __init__(self, message: str, *, code: str = "app_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class NotFoundError(AppException):
    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(message, code="not_found")


class ConflictError(AppException):
    def __init__(self, message: str = "Conflict") -> None:
        super().__init__(message, code="conflict")


class UnauthorizedError(AppException):
    def __init__(self, message: str = "Unauthorized") -> None:
        super().__init__(message, code="unauthorized")


class ForbiddenError(AppException):
    def __init__(self, message: str = "Forbidden") -> None:
        super().__init__(message, code="forbidden")


class ValidationAppError(AppException):
    """Business-rule validation separate from Pydantic HTTP 422."""

    def __init__(self, message: str, *, code: str = "validation_error") -> None:
        super().__init__(message, code=code)


class RateLimitError(AppException):
    def __init__(self, message: str = "Too many requests", *, retry_after_seconds: int | None = None) -> None:
        super().__init__(message, code="rate_limited")
        self.retry_after_seconds = retry_after_seconds


class ServiceUnavailableError(AppException):
    def __init__(self, message: str = "Service temporarily unavailable") -> None:
        super().__init__(message, code="service_unavailable")
