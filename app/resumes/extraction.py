from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Literal
from urllib.parse import urlparse

from app.validation.urls import normalize_http_url

DatePrecision = Literal["day", "month", "year"]

_MONTHS = {
    name: index
    for index, name in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        1,
    )
}
_MONTHS.update({name[:3]: index for name, index in _MONTHS.items()})
_CURRENT = {"current", "present", "till date", "ongoing", "now", "current role"}
_MONTH_NAME_PATTERN = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|[o0]ct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_DATE_TOKEN = re.compile(
    rf"(?P<value>\d{{1,2}}[/-]\d{{4}}|"
    rf"\d{{4}}(?:[-/]\d{{1,2}}(?:[-/]\d{{1,2}})?)?|"
    rf"{_MONTH_NAME_PATTERN}[' ]?\d{{2,4}})",
    re.IGNORECASE,
)
_DATE_VALUE_PATTERN = (
    rf"(?:\d{{1,2}}[/-]\d{{4}}|\d{{4}}(?:[-/]\d{{1,2}}(?:[-/]\d{{1,2}})?)?|"
    rf"{_MONTH_NAME_PATTERN}[' ]?\d{{2,4}})"
)
_DATE_RANGE = re.compile(
    rf"(?P<start>{_DATE_VALUE_PATTERN})\s*(?:-|–|—|to|until)\s*"
    rf"(?P<end>{_DATE_VALUE_PATTERN}|present|current|till date|ongoing|now|current role)",
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

_MODEL_COLLECTION_FIELDS = (
    "employments",
    "education",
    "internships",
    "freelance",
    "gig_platforms",
    "certifications",
    "projects",
    "skills",
    "portfolio_links",
)

_SKILL_WORD_PATTERN = r"sk(?:i|l|1)lls"
_SKILL_SECTION_HEADING = re.compile(
    rf"^(?:(?:core|technical|professional)\s+)?{_SKILL_WORD_PATTERN}"
    r"(?:\s+(?:&|and)\s+technologies)?\s*$",
    re.IGNORECASE,
)
_EXPLICIT_SKILL_LIST = re.compile(
    r"(?:"
    rf"\bmy\s+(?:core\s+)?{_SKILL_WORD_PATTERN}\s+(?:are|include)"
    rf"|\b(?:core|technical|professional)\s+{_SKILL_WORD_PATTERN}\s+(?:are|include)"
    rf"|\b(?:core\s+|technical\s+|professional\s+)?{_SKILL_WORD_PATTERN}\s*[:\-–—]"
    r")\s*(?P<items>[^.\n]+)",
    re.IGNORECASE,
)
_SKILL_LIST_SEPARATOR = re.compile(r"\s*(?:,|;|\||•|·)\s*(?:(?i:and)\s+)?|\s+/\s+|\s+(?i:and)\s+")
_RESUME_SECTION_HEADING = re.compile(
    r"^(?:candidate\s+profile|profile|summary|objective|experience|employment|work\s+history|"
    r"education|certifications?|projects?|portfolio|languages?|awards?|interests?|references?)\s*$",
    re.IGNORECASE,
)
_OCR_TITLE_TOKEN = re.compile(r"\b[A-Z][a-z]*[10][a-z]{2,}\b")


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
            parsed = (
                date.fromisoformat(value.strip())
                if fmt == "%Y-%m-%d"
                else datetime.strptime(value.strip(), fmt).date()
            )
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
    match = re.fullmatch(r"([a-z0]+)[' ]?(\d{2,4})", text)
    month_name = match.group(1).replace("0", "o", 1) if match else ""
    if match and month_name in _MONTHS:
        year = int(match.group(2))
        year += 2000 if year < 100 else 0
        return None, f"{year:04d}-{_MONTHS[month_name]:02d}", "month", False
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


def _normalize_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return candidate
    return None


def _normalize_link_fields(value: dict[str, Any]) -> dict[str, Any]:
    profile = dict(value.get("candidate_profile") or {})
    links = profile.get("profile_links") or []
    normalized_links = [link for item in links if (link := _normalize_url(item))][:20]
    if len(normalized_links) != len(links):
        value.setdefault("warnings", []).append("invalid_profile_link_removed")
    profile["profile_links"] = normalized_links
    value["candidate_profile"] = profile
    for key in ("portfolio_links",):
        links = value.get(key) or []
        normalized = [link for item in links if (link := _normalize_url(item))]
        if len(normalized) != len(links):
            value.setdefault("warnings", []).append(f"invalid_{key[:-6]}_removed")
        value[key] = normalized
    for claim_type in ("projects", "certifications"):
        for claim in value.get(claim_type) or []:
            if not isinstance(claim, dict):
                continue
            field = "url" if claim_type == "projects" else "credential_url"
            if claim_type == "certifications" and claim.get(field) is not None:
                claim[field] = normalize_http_url(claim.get(field))
            if claim.get(field) is not None and _normalize_url(claim.get(field)) is None:
                claim[field] = None
                value.setdefault("warnings", []).append(f"invalid_{field}_removed")
    for skill in value.get("skills") or []:
        if (
            isinstance(skill, dict)
            and isinstance(skill.get("name"), str)
            and len(skill["name"]) > 128
        ):
            skill["name"] = skill["name"][:128]
            value.setdefault("warnings", []).append("skill_name_truncated")
    return value


def _skill_list_items(value: str, *, require_list: bool) -> list[str]:
    items = [item.strip(" \t\r\n-–—•·|,;:.") for item in _SKILL_LIST_SEPARATOR.split(value)]
    items = [item for item in items if item]
    if require_list and len(items) < 2:
        return []
    return [item for item in items if len(item) <= 128 and len(item.split()) <= 6]


def _is_explicit_skill_heading(value: str) -> bool:
    return _SKILL_SECTION_HEADING.fullmatch(value.strip()) is not None


def _skill_comparison_key(value: str) -> str:
    """Normalize benign list punctuation without erasing meaningful skill symbols."""
    normalized = re.sub(r"\s*(?:,|;|\||•|·)\s*", " ", value.strip())
    return " ".join(normalized.casefold().split())


def _is_redundant_composite_skill(candidate: str, explicit_names: list[str]) -> bool:
    """Return true when source-backed skills completely compose a model-only candidate."""
    candidate_key = _skill_comparison_key(candidate)
    explicit_keys = {key for name in explicit_names if (key := _skill_comparison_key(name))}
    if not candidate_key or candidate_key in explicit_keys:
        return False

    candidate_tokens = tuple(candidate_key.split())
    supported = {
        tuple(key.split()): key
        for key in explicit_keys
        if key != candidate_key and len(key.split()) <= len(candidate_tokens)
    }
    if len(supported) < 2:
        return False

    def composed_from(index: int, used: frozenset[str]) -> bool:
        if index == len(candidate_tokens):
            return len(used) >= 2
        for tokens, key in supported.items():
            if key in used:
                continue
            end = index + len(tokens)
            if candidate_tokens[index:end] == tokens and composed_from(end, used | {key}):
                return True
        return False

    return composed_from(0, frozenset())


def _explicit_skill_names(extracted_text: str) -> list[str]:
    """Return only skills from high-confidence, explicitly labelled resume lists."""
    candidates: list[str] = []
    lines = [line.strip() for line in extracted_text.splitlines()]
    for index, line in enumerate(lines):
        if _is_explicit_skill_heading(line):
            for item_line in lines[index + 1 :]:
                if not item_line:
                    break
                if _RESUME_SECTION_HEADING.fullmatch(item_line):
                    break
                candidates.extend(_skill_list_items(item_line, require_list=False))
        for match in _EXPLICIT_SKILL_LIST.finditer(line):
            candidates.extend(_skill_list_items(match.group("items"), require_list=True))

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = " ".join(candidate.casefold().split())
        if key and key not in seen:
            seen.add(key)
            unique.append(" ".join(candidate.split()))
    return unique


def enrich_explicit_skills(payload: dict[str, Any], extracted_text: str) -> dict[str, Any]:
    """Merge explicit labelled skills without inferring from employers, titles, or prose."""
    value = dict(payload)
    explicit_names = _explicit_skill_names(extracted_text)
    skills: list[Any] = []
    seen: set[str] = set()
    for skill in value.get("skills") or []:
        if not isinstance(skill, dict) or not isinstance(skill.get("name"), str):
            skills.append(skill)
            continue
        item = dict(skill)
        item["name"] = " ".join(item["name"].strip(" \t\r\n,;|•·:").split())
        if _is_redundant_composite_skill(item["name"], explicit_names):
            value.setdefault("warnings", []).append("collapsed_explicit_skill_list_reconciled")
            continue
        key = _skill_comparison_key(item["name"])
        if not key or key in seen:
            continue
        seen.add(key)
        skills.append(item)
    for name in explicit_names:
        key = _skill_comparison_key(name)
        if key in seen:
            continue
        seen.add(key)
        skills.append({"name": name})
    value["skills"] = skills
    return value


def _ocr_comparison_text(value: str) -> str:
    text = re.sub(r"(?<=[A-Za-z])1(?=[A-Za-z])", "i", value)
    text = re.sub(r"(?<=[A-Za-z])0(?=[A-Za-z])", "o", text)
    return " ".join(text.casefold().split())


def _repair_source_corroborated_ocr_text(value: Any, extracted_text: str) -> tuple[Any, bool]:
    """Repair a narrow title-case OCR glyph class only when the source contains it verbatim."""
    if not isinstance(value, str):
        return value, False
    source_tokens = set(re.findall(r"\b[A-Za-z0-9]+\b", extracted_text))
    changed = False

    def replace(match: re.Match[str]) -> str:
        nonlocal changed
        token = match.group(0)
        if token not in source_tokens:
            return token
        changed = True
        return token.replace("1", "i").replace("0", "o")

    return _OCR_TITLE_TOKEN.sub(replace, value), changed


def normalize_ocr_structured_fields(payload: dict[str, Any], extracted_text: str) -> dict[str, Any]:
    """Normalize source-backed OCR glyph confusions without creating or reclassifying claims."""
    value = dict(payload)
    changed = False
    profile = dict(value.get("candidate_profile") or {})
    for field in ("full_name", "professional_headline"):
        profile[field], repaired = _repair_source_corroborated_ocr_text(
            profile.get(field), extracted_text
        )
        changed = changed or repaired

    role_titles = [
        claim.get("role_title")
        for claim in value.get("employments") or []
        if isinstance(claim, dict) and isinstance(claim.get("role_title"), str)
    ]
    headline = profile.get("professional_headline")
    if isinstance(headline, str):
        for role_title in role_titles:
            if headline.casefold() != role_title.casefold() and _ocr_comparison_text(
                headline
            ) == _ocr_comparison_text(role_title):
                profile["professional_headline"] = role_title
                changed = True
                break
    value["candidate_profile"] = profile

    employments: list[Any] = []
    for claim in value.get("employments") or []:
        if not isinstance(claim, dict):
            employments.append(claim)
            continue
        item = dict(claim)
        for field in ("company_name", "role_title"):
            item[field], repaired = _repair_source_corroborated_ocr_text(
                item.get(field), extracted_text
            )
            changed = changed or repaired
        employments.append(item)
    value["employments"] = employments
    if changed:
        value.setdefault("warnings", []).append("source_corroborated_ocr_text_normalized")
    return value


def _nearby_lines(claim: dict[str, Any], lines: list[str]) -> list[str]:
    needles = [claim.get("company_name"), claim.get("role_title")]
    needles = [_ocr_comparison_text(str(item)) for item in needles if item]
    if not needles:
        return []
    for needle in needles:
        for index, line in enumerate(lines):
            if needle in _ocr_comparison_text(line):
                return lines[max(0, index - 1) : min(len(lines), index + 3)]
    return []


def _uniquely_associated_employment_lines(claim: dict[str, Any], extracted_text: str) -> list[str]:
    """Return a small source block only when one claim anchor has one exact location."""
    lines = [line.strip() for line in extracted_text.splitlines()]
    anchors = [claim.get("company_name"), claim.get("role_title")]
    for anchor in anchors:
        if not isinstance(anchor, str) or not anchor.strip():
            continue
        needle = _ocr_comparison_text(anchor)
        matches = [
            index for index, line in enumerate(lines) if needle in _ocr_comparison_text(line)
        ]
        if len(matches) != 1:
            continue
        index = matches[0]
        block: list[str] = []
        for line in lines[index : min(len(lines), index + 5)]:
            if block and (not line or _RESUME_SECTION_HEADING.fullmatch(line)):
                break
            if line:
                block.append(line)
        return block
    return []


def _employment_date_evidence(
    claim: dict[str, Any], extracted_text: str
) -> dict[str, tuple[str | None, str | None, DatePrecision | None, bool]]:
    nearby = _uniquely_associated_employment_lines(claim, extracted_text)
    match = _DATE_RANGE.search(" ".join(nearby))
    if match is None:
        return {}
    start_date, start_display, start_precision, start_current = parse_resume_date(
        match.group("start")
    )
    end_date, end_display, end_precision, end_current = parse_resume_date(match.group("end"))
    if start_display is None or (start_date is None and start_precision is None):
        return {}
    return {
        "start": (
            start_date.isoformat() if start_date else None,
            start_display,
            start_precision,
            start_current,
        ),
        "end": (
            end_date.isoformat() if end_date else None,
            end_display,
            end_precision,
            end_current,
        ),
    }


def _apply_employment_date_evidence(
    claim: dict[str, Any],
    field: str,
    evidence: tuple[str | None, str | None, DatePrecision | None, bool] | None,
) -> None:
    exact, display, precision, current = evidence or (None, None, None, False)
    claim[field] = exact
    claim[f"{field}_display"] = display
    claim[f"{field}_precision"] = precision
    if field == "end_date" and current:
        claim["is_current"] = True


def reconcile_pdf_employment_dates(
    payload: dict[str, Any], textract_text: str, embedded_text: str
) -> dict[str, Any]:
    """Reconcile only explicit, claim-associated PDF date evidence after model parsing."""
    value = dict(payload)
    claims: list[Any] = []
    for claim in value.get("employments") or []:
        if not isinstance(claim, dict):
            claims.append(claim)
            continue
        item = dict(claim)
        warnings = list(item.get("warnings") or [])
        primary = _employment_date_evidence(item, textract_text)
        supplemental = _employment_date_evidence(item, embedded_text)
        for evidence_name, field in (("start", "start_date"), ("end", "end_date")):
            primary_value = primary.get(evidence_name)
            supplemental_value = supplemental.get(evidence_name)
            if primary_value and supplemental_value and primary_value != supplemental_value:
                _apply_employment_date_evidence(item, field, None)
                warnings.append(f"conflicting_{field}_pdf_evidence")
                continue
            chosen = primary_value or supplemental_value
            _apply_employment_date_evidence(item, field, chosen)
            if chosen and primary_value and supplemental_value:
                warnings.append(f"{field}_corroborated_by_hybrid_pdf_evidence")
            elif chosen and supplemental_value:
                warnings.append(f"{field}_recovered_from_embedded_pdf_evidence")
            elif chosen:
                warnings.append(f"{field}_recovered_from_textract_evidence")
            else:
                warnings.append(f"{field}_removed_without_explicit_pdf_evidence")
        item["warnings"] = list(dict.fromkeys(warnings))
        claims.append(item)
    value["employments"] = claims
    return value


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
                return {
                    "city": canonical,
                    "region": None,
                    "country": None,
                    "display": original,
                }, None
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


def normalize_extracted_payload(
    payload: dict[str, Any], extracted_text: str = ""
) -> dict[str, Any]:
    """Normalize partial dates and high-confidence location/date hints without inventing values."""
    value = dict(payload)
    if value.get("candidate_profile") is None:
        value["candidate_profile"] = {}
    profile = value.get("candidate_profile")
    if isinstance(profile, dict) and profile.get("profile_links") is None:
        profile["profile_links"] = []
    if value.get("warnings") is None:
        value["warnings"] = []
    for collection in _MODEL_COLLECTION_FIELDS:
        if value.get(collection) is None:
            value[collection] = []
    value = enrich_explicit_skills(value, extracted_text)
    value = normalize_ocr_structured_fields(value, extracted_text)
    for collection in _MODEL_COLLECTION_FIELDS:
        if collection == "portfolio_links" or not isinstance(value.get(collection), list):
            continue
        for claim in value[collection]:
            if not isinstance(claim, dict):
                continue
            if claim.get("warnings") is None:
                claim["warnings"] = []
            claim["source_type"] = "resume"
            claim["selected_for_import"] = False
    value = _normalize_link_fields(value)
    for collection in ("employments", "education"):
        claims = []
        for claim in value.get(collection) or []:
            if isinstance(claim, dict):
                item = dict(claim)
                if collection == "employments":
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
        value[collection] = claims
    return enrich_employment_claims(value, extracted_text)
