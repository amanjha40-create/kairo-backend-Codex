from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Literal

DatePrecision = Literal["day", "month", "year"]

_MONTHS = {
    name: index
    for index, name in enumerate(
        ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"),
        1,
    )
}
_MONTHS.update({name[:3]: index for name, index in _MONTHS.items()})
_CURRENT = {"current", "present", "till date", "ongoing", "now", "current role"}
_DATE_TOKEN = re.compile(
    r"(?P<value>\d{1,2}[/-]\d{4}|\d{4}(?:[-/]\d{1,2}(?:[-/]\d{1,2})?)?|(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)[' ]?\d{2,4})",
    re.IGNORECASE,
)
_DATE_VALUE_PATTERN = r"(?:\d{1,2}[/-]\d{4}|\d{4}(?:[-/]\d{1,2}(?:[-/]\d{1,2})?)?|(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)[' ]?\d{2,4})"
_DATE_RANGE = re.compile(
    rf"(?P<start>{_DATE_VALUE_PATTERN})\s*(?:-|–|—|to|until)\s*(?P<end>{_DATE_VALUE_PATTERN}|present|current|till date|ongoing|now|current role)",
    re.IGNORECASE,
)
_CITY_ALIASES = {
    "bangalore": "Bengaluru",
    "bengaluru": "Bengaluru",
    "gurgaon": "Gurugram",
    "gurugram": "Gurugram",
    "bombay": "Mumbai",
    "mumbai": "Mumbai",
    "new delhi": "New Delhi",
    "delhi": "Delhi",
    "delhi ncr": "Delhi NCR",
    "noida": "Noida",
    "pune": "Pune",
    "hyderabad": "Hyderabad",
    "chennai": "Chennai",
    "kolkata": "Kolkata",
}


def parse_resume_date(value: Any) -> tuple[date | None, str | None, DatePrecision | None, bool]:
    """Return exact date, display value, precision, and current-role marker."""
    if isinstance(value, date):
        return value, value.isoformat(), "day", False
    if not isinstance(value, str):
        return None, None, None, False
    text = " ".join(value.strip().casefold().split())
    if not text:
        return None, None, None, False
    if text in _CURRENT:
        return None, value.strip(), None, True
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            parsed = date.fromisoformat(value.strip()) if fmt == "%Y-%m-%d" else datetime.strptime(value.strip(), fmt).date()
            return parsed, parsed.isoformat(), "day", False
        except (ValueError, AttributeError):
            pass
    match = re.fullmatch(r"(\d{1,2})[/-](\d{4})", text)
    if match:
        month, year = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12:
            return None, f"{year:04d}-{month:02d}", "month", False
    match = re.fullmatch(r"(\d{4})[-/]?(\d{2})?", text)
    if match:
        year, month = int(match.group(1)), match.group(2)
        if month and 1 <= int(month) <= 12:
            return None, f"{year:04d}-{int(month):02d}", "month", False
        return None, f"{year:04d}", "year", False
    match = re.fullmatch(r"([a-z]+)[' ]?(\d{2,4})", text)
    if match and match.group(1) in _MONTHS:
        year = int(match.group(2))
        year += 2000 if year < 100 else 0
        return None, f"{year:04d}-{_MONTHS[match.group(1)]:02d}", "month", False
    return None, value.strip(), None, False


def _normalize_location(location: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(location, dict):
        return location
    value = dict(location)
    original_parts = [value.get("city"), value.get("region"), value.get("country")]
    city = value.get("city")
    if isinstance(city, str):
        cleaned = " ".join(city.split()).strip()
        value["city"] = _CITY_ALIASES.get(cleaned.casefold(), cleaned) or None
    if not value.get("display"):
        value["display"] = ", ".join(str(part) for part in original_parts if part)
    return value


def _nearby_lines(claim: dict[str, Any], lines: list[str]) -> list[str]:
    needles = [claim.get("company_name"), claim.get("role_title")]
    needles = [str(item).casefold() for item in needles if item]
    if not needles:
        return []
    for index, line in enumerate(lines):
        if any(needle in line.casefold() for needle in needles):
            return lines[max(0, index - 1): min(len(lines), index + 3)]
    return []


def _location_hint(lines: list[str]) -> tuple[dict[str, Any] | None, str | None]:
    for line in lines:
        original = line.strip()
        lowered = original.casefold()
        if any(token in lowered for token in ("remote", "work from home")):
            country = "India" if "india" in lowered else None
            return {"city": None, "region": None, "country": country, "display": original}, "remote"
        if "hybrid" in lowered:
            return {"city": None, "region": None, "country": None, "display": original}, "hybrid"
        for alias, canonical in sorted(_CITY_ALIASES.items(), key=lambda item: -len(item[0])):
            if re.search(rf"\b{re.escape(alias)}\b", lowered):
                return {"city": canonical, "region": None, "country": None, "display": original}, None
    return None, None


def enrich_employment_claims(payload: dict[str, Any], extracted_text: str) -> dict[str, Any]:
    lines = [line.strip() for line in extracted_text.splitlines() if line.strip()]
    if not lines:
        return payload
    value = dict(payload)
    claims = []
    for claim in value.get("employments") or []:
        if not isinstance(claim, dict):
            claims.append(claim)
            continue
        item = dict(claim)
        nearby = _nearby_lines(item, lines)
        for match in _DATE_RANGE.finditer(" ".join(nearby)):
            if not item.get("start_date") and not item.get("start_date_display"):
                _, display, precision, _ = parse_resume_date(match.group("start"))
                if display and precision:
                    item["start_date_display"], item["start_date_precision"] = display, precision
            if not item.get("end_date") and not item.get("end_date_display"):
                _, display, precision, current = parse_resume_date(match.group("end"))
                if current:
                    item["is_current"] = True
                if display:
                    item["end_date_display"] = display
                    if precision:
                        item["end_date_precision"] = precision
            break
        if not item.get("location"):
            location, arrangement = _location_hint(nearby)
            if location:
                item["location"] = location
            if arrangement and not item.get("work_arrangement"):
                item["work_arrangement"] = arrangement
        claims.append(item)
    value["employments"] = claims
    return value


def normalize_extracted_payload(payload: dict[str, Any], extracted_text: str = "") -> dict[str, Any]:
    """Normalize partial dates and high-confidence location/date hints without inventing values."""
    value = dict(payload)
    claims = []
    for claim in value.get("employments") or []:
        if isinstance(claim, dict):
            item = dict(claim)
            item["location"] = _normalize_location(item.get("location"))
            for field in ("start_date", "end_date"):
                parsed, display, precision, is_current = parse_resume_date(item.get(field))
                if parsed is not None:
                    item[field] = parsed.isoformat()
                    item[f"{field}_display"] = display
                    item[f"{field}_precision"] = precision
                elif display and precision:
                    item[field] = None
                    item[f"{field}_display"] = display
                    item[f"{field}_precision"] = precision
                elif is_current and field == "end_date":
                    item[field] = None
                    item["end_date_display"] = display
                    item["is_current"] = True
            claims.append(item)
        else:
            claims.append(claim)
    value["employments"] = claims
    return enrich_employment_claims(value, extracted_text)
