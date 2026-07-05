"""Request-scoped context for logs — propagated via contextvars (async-safe)."""

from __future__ import annotations

import contextvars
from typing import Any

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("logging_request_id", default=None)
_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("logging_correlation_id", default=None)
_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("logging_user_id", default=None)


def reset_request_context() -> None:
    """Clear all context vars — called after request completes."""

    _request_id.set(None)
    _correlation_id.set(None)
    _user_id.set(None)


def bind_request_context(
    *,
    request_id: str | None = None,
    correlation_id: str | None = None,
) -> None:
    """Attach IDs for the current async task (typically one HTTP request)."""

    if request_id is not None:
        _request_id.set(request_id)
    if correlation_id is not None:
        _correlation_id.set(correlation_id)


def bind_user_context(user_id: str | None) -> None:
    """Call from auth dependencies after resolving the current user (optional)."""

    _user_id.set(user_id)


def get_request_id() -> str | None:
    return _request_id.get()


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def get_user_id() -> str | None:
    return _user_id.get()


def context_as_dict() -> dict[str, Any]:
    """Snapshot for debugging or manual extra={} merges."""

    return {
        "request_id": _request_id.get(),
        "correlation_id": _correlation_id.get(),
        "user_id": _user_id.get(),
    }
