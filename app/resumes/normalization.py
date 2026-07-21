from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from calendar import monthrange
from datetime import date
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return re.sub(r"[^\w]+", " ", normalized).strip()


def normalize_url(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.casefold(), parsed.path.rstrip("/"), parsed.query, ""))


def payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def stable_claim_id(parsed_result_id: UUID, claim_type: str, ordinal: int, payload: dict[str, Any]) -> str:
    source_reference = payload.get("source_text_reference") or ""
    identity = {key: payload.get(key) for key in sorted(payload) if key not in {"confidence", "warnings"}}
    material = f"{parsed_result_id}:{claim_type}:{ordinal}:{source_reference}:{payload_hash(identity)}"
    return hashlib.sha256(material.encode()).hexdigest()


def normalize_date(value: date | str | None) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def normalize_review_date(value: date | str | None, display: str | None = None, *, is_end: bool = False) -> tuple[str | None, str | None]:
    """Convert resume month/year claims to contract dates without inventing precision."""
    raw = value.isoformat() if isinstance(value, date) else value or display
    if not raw:
        return None, None
    raw = raw.strip()
    if raw.casefold() in {"present", "current", "ongoing", "now", "till date", "current role"}:
        return None, None
    match = re.fullmatch(r"(\d{4})-(\d{2})(?:-(\d{2}))?", raw)
    if match:
        year, month, day = int(match.group(1)), int(match.group(2)), match.group(3)
        if not 1 <= month <= 12:
            return None, None
        if day:
            try:
                return date(year, month, int(day)).isoformat(), "day"
            except ValueError:
                return None, None
        return date(year, month, monthrange(year, month)[1] if is_end else 1).isoformat(), "month"
    year_match = re.fullmatch(r"(\d{4})", raw)
    if year_match:
        year = int(year_match.group(1))
        return date(year, 12 if is_end else 1, 31 if is_end else 1).isoformat(), "year"
    month_match = re.fullmatch(
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[ '\u2019-]*(\d{2}|\d{4})",
        raw,
        re.IGNORECASE,
    )
    if month_match:
        month = ("jan feb mar apr may jun jul aug sep oct nov dec".split().index(month_match.group(1)[:3].lower()) + 1)
        year = int(month_match.group(2))
        if year < 100:
            year += 2000
        return date(year, month, monthrange(year, month)[1] if is_end else 1).isoformat(), "month"
    return None, None
def date_ranges_overlap(
    start_a: date | str | None,
    end_a: date | str | None,
    start_b: date | str | None,
    end_b: date | str | None,
) -> bool:
    start_a = normalize_date(start_a)
    end_a = normalize_date(end_a)
    start_b = normalize_date(start_b)
    end_b = normalize_date(end_b)
    if not start_a or not start_b:
        return False
    high = date.max
    return start_a <= (end_b or high) and start_b <= (end_a or high)
