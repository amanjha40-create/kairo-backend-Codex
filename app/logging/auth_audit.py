"""Allowlisted auth attribution; no bearer credentials or raw client metadata."""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from datetime import UTC, datetime
from uuid import UUID

from app.logging.context import get_user_id

EVENTS = frozenset(
    {
        "AUTH_REFRESH_ROTATE",
        "AUTH_REFRESH_FAMILY_REVOKE",
        "AUTH_LOGOUT_REQUEST",
        "AUTH_LOGOUT_SESSION_REVOKED",
        "AUTH_SESSION_REVOKE",
        "AUTH_SESSION_REVOKE_ALL",
    }
)
CLIENTS = frozenset({"android_webview", "android_browser", "ios_browser", "browser", "other"})
_capture: contextvars.ContextVar[dict | None] = contextvars.ContextVar("auth_audit", default=None)
logger = logging.getLogger("kairo.safe_auth_audit")
logger.propagate = False
logger.addHandler(logging.NullHandler())


def _uuid(value):
    if not isinstance(value, (UUID, str)):
        return None
    try:
        return str(UUID(str(value)))
    except ValueError:
        return None


def _client(user_agent: str) -> str:
    agent = user_agent[:1024].lower()
    if "android" in agent:
        return "android_webview" if "; wv" in agent else "android_browser"
    if "iphone" in agent or "ipad" in agent:
        return "ios_browser"
    if any(name in agent for name in ("mozilla/", "chrome/", "safari/", "firefox/")):
        return "browser"
    return "other"


class AuthAuditFormatter(logging.Formatter):
    def __init__(self, environment):
        super().__init__()
        self.environment = (
            environment
            if isinstance(environment, str)
            and environment
            in {
                "production",
                "staging",
                "development",
                "test",
            }
            else "unknown"
        )

    def format(self, record):
        data = getattr(record, "audit", {})
        data = data if type(data) is dict else {}
        event = data.get("event")
        endpoint = data.get("endpoint")
        status = data.get("http_status")
        timestamp = data.get("timestamp")
        # Build a new fixed-field object; never serialize arbitrary LogRecord extras.
        safe = {
            "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else None,
            "event": event
            if isinstance(event, str) and event in EVENTS
            else "AUTH_AUDIT_INVALID_EVENT",
            "environment": self.environment,
            "endpoint": endpoint
            if isinstance(endpoint, str)
            and len(endpoint) <= 200
            and re.fullmatch(r"/api/v1/[A-Za-z0-9_/{}/-]+", endpoint)
            else None,
            "http_status": status if type(status) is int and 100 <= status <= 599 else None,
            "client_class": data.get("client_class")
            if isinstance(data.get("client_class"), str) and data.get("client_class") in CLIENTS
            else "other",
        }
        for key in (
            "user_id",
            "actor_user_id",
            "session_id",
            "family_id",
            "successor_session_id",
            "excluded_family_id",
            "request_id",
            "correlation_id",
        ):
            safe[key] = _uuid(data.get(key))
        return json.dumps(safe, separators=(",", ":"))


def configure_auth_audit_logging(environment):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(AuthAuditFormatter(environment))
    logger.handlers[:] = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False


def begin_auth_audit(request_id, correlation_id, user_agent):
    return _capture.set(
        {
            "request_id": _uuid(request_id),
            "correlation_id": _uuid(correlation_id),
            "client_class": _client(user_agent),
            "events": [],
        }
    )


def auth_audit(
    event,
    *,
    user_id=None,
    session_id=None,
    family_id=None,
    successor_session_id=None,
    excluded_family_id=None,
):
    """Record committed effects, or an explicit request event; never affect auth behavior."""
    try:
        if event not in EVENTS:
            return
        data = {
            "timestamp": datetime.now(UTC),
            "event": event,
            "user_id": _uuid(user_id),
            "actor_user_id": _uuid(get_user_id()),
            "session_id": _uuid(session_id),
            "family_id": _uuid(family_id),
            "successor_session_id": _uuid(successor_session_id),
            "excluded_family_id": _uuid(excluded_family_id),
        }
        capture = _capture.get()
        if capture is None:
            logger.info(event, extra={"audit": data})
        elif len(capture["events"]) < 16:
            capture["events"].append(data)
    except Exception:
        # Observability failure must not turn a committed auth operation into an error/retry.
        pass


def finish_auth_audit(token, *, endpoint, status):
    try:
        capture = _capture.get()
        if capture:
            for data in capture["events"]:
                payload = {
                    **data,
                    "request_id": capture["request_id"],
                    "correlation_id": capture["correlation_id"],
                    "client_class": capture["client_class"],
                    "endpoint": endpoint,
                    "http_status": status,
                }
                logger.info(payload["event"], extra={"audit": payload})
    except Exception:
        pass
    finally:
        _capture.reset(token)
