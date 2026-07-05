"""Logging filters — inject stable correlation fields onto every LogRecord."""

from __future__ import annotations

import logging

from app.logging.context import get_correlation_id, get_request_id, get_user_id


class ServiceMetadataFilter(logging.Filter):
    """Adds `service` and `environment` from deployment settings."""

    def __init__(self, service: str, environment: str) -> None:
        super().__init__()
        self._service = service
        self._environment = environment

    def filter(self, record: logging.LogRecord) -> bool:
        setattr(record, "service", self._service)
        setattr(record, "environment", self._environment)
        return True


class RequestContextFilter(logging.Filter):
    """Adds request correlation fields when running inside HTTP middleware scope."""

    def filter(self, record: logging.LogRecord) -> bool:
        setattr(record, "request_id", get_request_id() or "")
        setattr(record, "correlation_id", get_correlation_id() or "")
        setattr(record, "user_id", get_user_id() or "")
        return True
