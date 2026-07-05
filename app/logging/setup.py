"""One-time logging configuration — root logger, library loggers, handlers, filters."""

from __future__ import annotations

import logging
import sys

from pythonjsonlogger.jsonlogger import JsonFormatter

from app.config import get_settings
from app.logging.filters import RequestContextFilter, ServiceMetadataFilter


class KairoJsonFormatter(JsonFormatter):
    """Ensures `logger.info(..., extra={...})` HTTP fields appear in JSON output."""

    _MERGED_EXTRA = frozenset({
        "event",
        "http_method",
        "http_path",
        "http_route",
        "status_code",
        "duration_ms",
        "client_host",
    })

    def add_fields(
        self,
        log_record: dict,
        record: logging.LogRecord,
        message_dict: dict,
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        for key in self._MERGED_EXTRA:
            if hasattr(record, key):
                val = getattr(record, key)
                if val is not None:
                    log_record[key] = val


def configure_logging() -> None:
    """Configure root + third-party loggers once at process startup (lifespan)."""

    settings = get_settings()
    level_name = settings.log_level.upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    if settings.log_json:
        fmt = (
            "%(asctime)s %(levelname)s %(name)s %(message)s %(service)s %(environment)s "
            "%(request_id)s %(correlation_id)s %(user_id)s %(pathname)s %(lineno)d"
        )
        formatter = KairoJsonFormatter(
            fmt,
            rename_fields={
                "levelname": "level",
                "asctime": "timestamp",
                "pathname": "source_path",
                "lineno": "source_line",
            },
            json_default=str,
        )
    else:
        formatter = logging.Formatter(
            fmt=(
                "%(asctime)s | %(levelname)s | %(name)s | %(message)s | "
                "req=%(request_id)s corr=%(correlation_id)s uid=%(user_id)s"
            ),
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handler.setFormatter(formatter)
    handler.addFilter(
        ServiceMetadataFilter(service=settings.app_name, environment=settings.app_env.value),
    )
    handler.addFilter(RequestContextFilter())
    root.addHandler(handler)

    logging.getLogger("uvicorn").setLevel(level)
    if settings.log_access_enabled:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    else:
        logging.getLogger("uvicorn.access").setLevel(level)

    logging.getLogger("uvicorn.error").setLevel(level)

    sa_level = logging.DEBUG if level <= logging.DEBUG else logging.WARNING
    logging.getLogger("sqlalchemy.engine").setLevel(sa_level)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Namespaced logger — use `__name__` of the calling module."""

    return logging.getLogger(name)
