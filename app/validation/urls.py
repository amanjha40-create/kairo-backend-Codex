"""Small shared helpers for candidate-supplied public web links."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def normalize_http_url(value: str | None) -> str | None:
    """Return a safe absolute HTTP(S) URL, accepting a user-entered bare domain."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlsplit(candidate)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        return None
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path, parsed.query, ""))
