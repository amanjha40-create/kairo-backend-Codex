"""Backward-compatible logging exports — prefer `from app.logging import ...`."""

from app.logging import configure_logging as setup_logging, get_logger, log_extra

__all__ = ["get_logger", "log_extra", "setup_logging"]
