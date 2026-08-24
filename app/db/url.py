"""Database URL construction, transformations, and safe redaction helpers."""

from __future__ import annotations

import re

from sqlalchemy.engine import URL, make_url

SUPPORTED_RUNTIME_DRIVER = "postgresql+asyncpg"
SUPPORTED_MIGRATION_DRIVERS = {"postgresql+asyncpg", "postgresql+psycopg"}

_URL_RE = re.compile(
    r"(?P<url>(?:postgres(?:ql)?(?:\+\w+)?|redis(?:s)?|mysql(?:\+\w+)?)://[^\s'\"<>()]+)",
    re.IGNORECASE,
)
_KEY_VALUE_SECRET_RE = re.compile(
    r"(?P<key>\b(?:password|passwd|pwd|secret|token|apikey|api_key)\b)"
    r"(?P<separator>\s*[:=]\s*)"
    r"(?P<quote>['\"]?)"
    r"(?P<value>[^,'\"\s}]+)"
    r"(?P=quote)",
    re.IGNORECASE,
)


def build_database_url(
    *,
    drivername: str,
    username: str,
    password: str,
    host: str,
    port: int,
    database: str,
    sslmode: str | None = None,
) -> str:
    """Build a canonical database URL from structured components."""

    query = {"sslmode": sslmode} if sslmode else {}
    url = URL.create(
        drivername=drivername,
        username=username,
        password=password,
        host=host,
        port=port,
        database=database,
        query=query,
    )
    return url.render_as_string(hide_password=False)


def build_async_database_config(database_url: str) -> tuple[URL, dict[str, str]]:
    """Translate libpq's ``sslmode`` query option for asyncpg."""

    url = make_url(database_url)
    query = dict(url.query)
    sslmode = query.pop("sslmode", None)
    connect_args = {"ssl": sslmode} if sslmode else {}
    return url.set(query=query), connect_args


def build_sync_database_url(database_url: str) -> str:
    """Select psycopg for Alembic while preserving libpq query options."""

    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    return database_url


def redact_connection_secrets(value: str) -> str:
    """Redact credential-bearing connection text without suppressing context."""

    redacted = _URL_RE.sub(_redact_url_match, value)
    return _KEY_VALUE_SECRET_RE.sub(_redact_key_value_match, redacted)


def _redact_url_match(match: re.Match[str]) -> str:
    raw = match.group("url")
    try:
        return make_url(raw).render_as_string(hide_password=True)
    except Exception:
        if "@" not in raw or "://" not in raw:
            return raw
        prefix, remainder = raw.split("://", 1)
        if "@" not in remainder:
            return raw
        credentials, suffix = remainder.split("@", 1)
        if ":" not in credentials:
            return raw
        username, _password = credentials.split(":", 1)
        return f"{prefix}://{username}:***@{suffix}"


def _redact_key_value_match(match: re.Match[str]) -> str:
    return (
        f"{match.group('key')}{match.group('separator')}{match.group('quote')}"
        f"***{match.group('quote')}"
    )
