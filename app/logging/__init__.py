"""Structured logging API — correlation IDs, JSON/plain output, access logs."""

from __future__ import annotations

from typing import Any

from app.logging.context import (
    bind_request_context,
    bind_user_context,
    context_as_dict,
    get_correlation_id,
    get_request_id,
    get_user_id,
    reset_request_context,
)
from app.logging.setup import configure_logging, get_logger

setup_logging = configure_logging


def log_extra(**kwargs: Any) -> dict[str, Any]:
    """Merge into `logger.info(..., extra=log_extra(...))` safely."""

    return kwargs


__all__ = [
    "bind_request_context",
    "bind_user_context",
    "configure_logging",
    "context_as_dict",
    "get_correlation_id",
    "get_logger",
    "get_request_id",
    "get_user_id",
    "log_extra",
    "reset_request_context",
    "setup_logging",
]
