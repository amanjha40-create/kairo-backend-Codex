"""Process-local runtime metadata for safe operational introspection."""

from __future__ import annotations

from datetime import UTC, datetime

APP_STARTED_AT = datetime.now(tz=UTC)

