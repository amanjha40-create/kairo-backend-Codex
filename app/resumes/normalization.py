from __future__ import annotations

import hashlib
import json
import re
import unicodedata
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
