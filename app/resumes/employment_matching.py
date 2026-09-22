"""Comparison-only employment identity; never rewrite Career facts."""

import re
from calendar import monthrange
from datetime import date
from difflib import SequenceMatcher
from typing import Any

from app.resumes.normalization import normalize_review_date, normalize_text, payload_hash

_LEGAL_ENDING = re.compile(
    r" (?:private limited|pvt ltd|private ltd|pvt limited|limited|ltd|pvt|llc|llp|"
    r"incorporated|inc|corporation|corp)$"
)
_SENIORITY = {"senior", "junior", "lead", "principal", "head", "chief", "intern", "trainee"}
_LEVEL_ALIASES = {"sr": "senior", "jr": "junior"}


def employer_identity(value: str | None) -> str:
    value = normalize_text(value)
    # Strip suffixes only at the end, and never remove the entire identity.
    for _ in range(3):
        stripped = _LEGAL_ENDING.sub("", value)
        if stripped == value:
            break
        value = stripped
    return value


def claim_date(payload: dict[str, Any], field: str) -> tuple[date | None, str | None]:
    value, precision = normalize_review_date(
        payload.get(field), payload.get(f"{field}_display"), is_end=field == "end_date"
    )
    return (
        date.fromisoformat(value) if value else None,
        payload.get(f"{field}_precision") or precision,
    )


def _same_date(parsed: date | None, precision: str | None, existing: date | None) -> bool:
    if not parsed or not existing or precision == "year":
        return False
    if precision == "month":
        return (parsed.year, parsed.month) == (existing.year, existing.month)
    return parsed == existing


def employment_match(payload: dict[str, Any], row: Any) -> tuple[str | None, list[str]]:
    employer = employer_identity(payload.get("company_name"))
    if not employer or employer != employer_identity(row.employer_legal_name):
        return None, []
    title = normalize_text(payload.get("role_title"))
    existing_title = normalize_text(row.job_title)
    start, start_precision = claim_date(payload, "start_date")
    end, end_precision = claim_date(payload, "end_date")
    current = payload.get("is_current") is True
    same_dates = _same_date(start, start_precision, row.start_date) and (
        (current and row.end_date is None)
        or (not current and _same_date(end, end_precision, row.end_date))
    )
    imported_type = payload.get("employment_type")
    existing_type = getattr(row, "employment_type", None)
    conflicting_type = (
        imported_type not in {None, "", "other"}
        and existing_type not in {None, "", "other"}
        and imported_type != existing_type
    )
    if title and title == existing_title and same_dates and not conflicting_type:
        return "exact_match", ["normalized_employer_title_dates_match"]
    # Year-only values are bounds, not evidence of exact employment identity.
    start_low = date(start.year, 1, 1) if start and start_precision == "year" else start
    end_high = date(end.year, 12, 31) if end and end_precision == "year" else end
    if start and start_precision == "month":
        start_low = date(start.year, start.month, 1)
    if end and end_precision == "month":
        end_high = date(end.year, end.month, monthrange(end.year, end.month)[1])
    if (end_high and row.start_date and end_high < row.start_date) or (
        row.end_date and start_low and row.end_date < start_low
    ):
        return None, []
    if title and existing_title and title != existing_title:
        words, existing_words = set(title.split()), set(existing_title.split())
        levels = {_LEVEL_ALIASES.get(word, word) for word in words} & _SENIORITY
        existing_levels = {_LEVEL_ALIASES.get(word, word) for word in existing_words} & _SENIORITY
        if levels != existing_levels:
            return None, []
        overlap = len(words & existing_words) / max(1, min(len(words), len(existing_words)))
        # Similar wording can suggest review, never an automatic link/merge.
        similar = SequenceMatcher(None, title, existing_title, autojunk=False).ratio() >= 0.8
        if overlap < 0.5 and not similar:
            return None, []
    return "possible_match", ["employment_identity_requires_review"]


def match_fingerprint(payload: dict[str, Any], row: Any) -> str:
    return payload_hash(
        {
            "import": payload,
            "existing": [
                str(row.id),
                row.employer_legal_name,
                row.job_title,
                row.start_date,
                row.end_date,
                row.verification_status,
                getattr(row, "employment_type", None),
            ],
        }
    )


def unchanged_import(payload: dict[str, Any], row: Any) -> bool:
    """An identical prior import can be replayed without guessing missing dates."""
    return (
        employer_identity(payload.get("company_name")) == employer_identity(row.employer_legal_name)
        and normalize_text(payload.get("role_title")) == normalize_text(row.job_title)
        and claim_date(payload, "start_date")[0] == row.start_date
        and claim_date(payload, "end_date")[0] == row.end_date
    )
