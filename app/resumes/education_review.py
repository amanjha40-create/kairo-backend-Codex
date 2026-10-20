"""Education-only date normalization with final validation and safe conflict codes."""
from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import ValidationError

from app.exceptions import ValidationAppError
from app.resumes.normalization import normalize_review_date
from app.resumes.review_schemas import EducationReviewClaim

ONGOING = frozenset({"present", "current", "ongoing", "now", "till date", "current role"})
DATE_ERRORS = frozenset({"current_claim_has_end_date", "end_date_before_start_date"})


def _conflict(code: str) -> ValidationAppError:
    return ValidationAppError("Resolve the Education review date conflict", code=code)


def _validate(payload: dict[str, Any]) -> EducationReviewClaim:
    try:
        return EducationReviewClaim.model_validate(payload)
    except ValidationError as exc:
        for error in exc.errors(include_input=False, include_url=False):
            reason = str(error.get("ctx", {}).get("error", ""))
            if reason in DATE_ERRORS:
                raise _conflict(reason) from None
        raise _conflict("invalid_review_item") from None


def _date(value: Any, *, is_end: bool) -> tuple[str | None, str | None]:
    if value is None or value == "":
        return None, None
    if not isinstance(value, (date, str)):
        raise _conflict("invalid_education_date")
    try:
        normalized, precision = normalize_review_date(value, is_end=is_end)
    except (ValueError, TypeError, OverflowError):
        raise _conflict("invalid_education_date") from None
    if normalized is None:
        raise _conflict("invalid_education_date")
    return normalized, precision


def normalize_education_review(payload: dict[str, Any]) -> dict[str, Any]:
    """Never mutate input, discard conflicts, or infer a change to current-study state."""
    result = dict(payload)
    # Validate non-date structure/coercion first, but validate real dates AFTER normalization.
    shape = _validate({**result, "start_date": None, "end_date": None})
    for field, is_end in (("start_date", False), ("end_date", True)):
        raw, display = result.get(field), result.get(f"{field}_display")
        precision = result.get(f"{field}_precision")
        ongoing = (
            is_end and shape.is_current is True and isinstance(display, str)
            and display.strip().casefold() in ONGOING
        )
        if is_end and shape.is_current is True:
            if raw not in (None, "") or (display not in (None, "") and not ongoing):
                raise _conflict("current_claim_has_end_date")
        canonical, canonical_precision = _date(raw, is_end=is_end)
        alias, alias_precision = (None, None) if ongoing else _date(display, is_end=is_end)
        if canonical and alias and canonical != alias:
            raise _conflict("education_date_alias_conflict")
        normalized = canonical or alias
        inferred = alias_precision or canonical_precision
        if normalized and precision:
            if alias_precision and precision != alias_precision:
                raise _conflict("education_date_precision_conflict")
            if precision in {"month", "year"}:
                truncated = normalized[:7] if precision == "month" else normalized[:4]
                if _date(truncated, is_end=is_end)[0] != normalized:
                    raise _conflict("education_date_precision_conflict")
            elif inferred and inferred != precision:
                raise _conflict("education_date_precision_conflict")
        result[field] = normalized
        # Standalone precision remains metadata, never a source from which to invent a date.
        result[f"{field}_precision"] = precision or inferred
    return _validate(result).model_dump(mode="json")
