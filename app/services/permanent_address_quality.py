"""Pure Places V2 target-quality policy; no residence decision or provider I/O."""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field

POLICY_VERSION = "components-v1"
# Only a full component match may substitute for an unrecognized textual variant.
# This is not a replacement global score cutoff; explicit contradictions veto it.
HIGH_COMPONENT_SCORE = 1.0
_WORDS = {"rd": "road", "st": "street", "ave": "avenue", "blvd": "boulevard"}
_CITY_ALIASES = {
    "bangalore": "bengaluru",
    "bombay": "mumbai",
    "madras": "chennai",
    "calcutta": "kolkata",
}
_REGIONS = {
    "andhra pradesh": "ap",
    "arunachal pradesh": "ar",
    "assam": "as",
    "bihar": "br",
    "chhattisgarh": "ct",
    "goa": "ga",
    "gujarat": "gj",
    "haryana": "hr",
    "himachal pradesh": "hp",
    "jharkhand": "jh",
    "karnataka": "ka",
    "kerala": "kl",
    "madhya pradesh": "mp",
    "maharashtra": "mh",
    "manipur": "mn",
    "meghalaya": "ml",
    "mizoram": "mz",
    "nagaland": "nl",
    "odisha": "or",
    "orissa": "or",
    "punjab": "pb",
    "rajasthan": "rj",
    "sikkim": "sk",
    "tamil nadu": "tn",
    "telangana": "ts",
    "tripura": "tr",
    "uttar pradesh": "up",
    "uttarakhand": "ut",
    "west bengal": "wb",
    "delhi": "dl",
    "nct of delhi": "dl",
    "jammu and kashmir": "jk",
    "ladakh": "la",
    "puducherry": "py",
    "chandigarh": "ch",
    "lakshadweep": "ld",
    "andaman and nicobar islands": "an",
    "dadra and nagar haveli and daman and diu": "dh",
}


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.findall(r"[^\W_]+", text, flags=re.UNICODE))


def street_normalize(value: object) -> str:
    return " ".join(_WORDS.get(w, w) for w in normalize(value).split())


def _region(value: object) -> str:
    value = normalize(value)
    if value.startswith("in "):
        value = value[3:]
    return _REGIONS.get(value, value)


def _score(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and 0 <= value <= 1 else None


@dataclass(frozen=True)
class TargetDecision:
    classification: str
    quality: str | None = None
    radius_m: int | None = None
    selected_index: int | None = None
    warnings: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    candidates: tuple[dict, ...] = field(default=(), repr=False)

    @property
    def eligible(self) -> bool:
        return self.selected_index is not None


def _candidate(item: dict, query: dict) -> dict:
    address = item.get("Address") or {}
    match = item.get("MatchScores") or {}
    provided_scores = (match.get("Components") or {}).get("Address") or {}
    scores = {
        key: _score(provided_scores[key])
        for key in (
            "Country",
            "Region",
            "Locality",
            "PostalCode",
            "AddressNumber",
            "Building",
            "District",
        )
        if key in provided_scores
    }
    wanted_country = normalize(query.get("Country"))
    country = address.get("Country") or {}
    country_ok = wanted_country in {"in", "ind", "india"} and (
        country.get("Code3") == "IND" or country.get("Code2") == "IN"
    )
    reasons = []
    warnings = []
    checks = {"country": country_ok}
    if not country_ok:
        reasons.append("country_mismatch")

    region = address.get("Region") or {}
    expected_region = _region(query.get("Region"))
    returned_regions = {_region(region.get("Name")), _region(region.get("Code"))} - {""}
    checks["state"] = not expected_region or expected_region in returned_regions
    if expected_region and not checks["state"]:
        # Do not let a score override a known different state, even at 1.0.
        known = set(_REGIONS.values())
        conflict = expected_region in known and bool(returned_regions & known)
        checks["state"] = (
            bool(returned_regions) and not conflict and scores.get("Region") == HIGH_COMPONENT_SCORE
        )
    if not checks["state"]:
        reasons.append("state_mismatch")

    expected_city = normalize(query.get("Locality"))
    returned_city = normalize(address.get("Locality"))
    city_exact = _CITY_ALIASES.get(expected_city, expected_city) == _CITY_ALIASES.get(
        returned_city, returned_city
    )
    checks["city"] = not expected_city or (bool(returned_city) and city_exact)
    if expected_city and not checks["city"]:
        # A strong score is useful audit data but cannot erase two distinct cities.
        reasons.append("locality_mismatch")

    expected_pin = normalize(query.get("PostalCode"))
    returned_pin = normalize(address.get("PostalCode"))
    checks["pin"] = not expected_pin or (
        bool(re.fullmatch(r"[1-9][0-9]{5}", expected_pin)) and expected_pin == returned_pin
    )
    if not checks["pin"]:
        reasons.append("pin_mismatch_or_missing")

    expected_street = street_normalize(query.get("Street"))
    returned_street = street_normalize(address.get("Street"))
    checks["street"] = bool(
        expected_street and returned_street and expected_street == returned_street
    )
    if not checks["street"]:
        reasons.append("street_missing_or_mismatch")
    # AWS's current Geocode MatchScores.Address schema has no Street member.
    # Use the returned Street text; do not treat Overall or Title as a street score.

    expected_number = normalize(query.get("AddressNumber"))
    returned_number = normalize(address.get("AddressNumber"))
    mismatch = bool(expected_number and expected_number != returned_number)
    if mismatch:
        warnings.append("address_number_mismatch")
        if not all(query.get(key) for key in ("Region", "Locality", "PostalCode", "Street")):
            reasons.append("number_warning_requires_complete_structure")

    # Exact normalized agreement does not need a numeric cutoff. Keep lower
    # component scores as warnings; malformed supplied scores fail closed.
    for component, label in (
        ("Country", "country"),
        ("Region", "state"),
        ("Locality", "city"),
        ("PostalCode", "pin"),
    ):
        if component in provided_scores and scores.get(component) is None:
            reasons.append(label + "_component_score_invalid")
        elif component in provided_scores and scores[component] < HIGH_COMPONENT_SCORE:
            warnings.append(label + "_component_score_below_full")

    place_type = item.get("PlaceType")
    quality = None
    if place_type == "PointAddress" and not item.get("EstimatedPointAddress", False):
        quality = "precise_address"
    elif place_type == "InterpolatedAddress" and not item.get("EstimatedPointAddress", False):
        quality = "approximate_address"
        if not all(query.get(key) for key in ("Region", "Locality", "PostalCode", "Street")):
            reasons.append("approximate_requires_complete_structure")
    else:
        reasons.append("broad_or_unsupported_place_type")
    point = item.get("Position") or []
    coordinates_ok = (
        isinstance(point, (list, tuple))
        and len(point) == 2
        and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            for v in point
        )
        and -180 <= point[0] <= 180
        and -90 <= point[1] <= 90
    )
    if not coordinates_ok:
        reasons.append("invalid_position")
    return {
        "place_type": place_type,
        "overall_score": _score(match.get("Overall")),
        "component_scores": scores,
        "component_matches": checks,
        "street_score_available": False,
        "number_mismatch": mismatch,
        "quality": quality,
        "eligible": not reasons,
        "reasons": reasons,
        "warnings": warnings,
    }


def evaluate_targets(items: list[dict], query: dict, *, max_results: int = 10) -> TargetDecision:
    """No coordinate/address values leave this safe decision object."""
    candidates = tuple(_candidate(item, query) for item in items)
    eligible = [i for i, value in enumerate(candidates) if value["eligible"]]
    if len(items) >= max_results:
        return TargetDecision(
            "ADDRESS_NEEDS_REVIEW", reasons=("candidate_list_truncated",), candidates=candidates
        )
    if any(not v["component_matches"]["country"] for v in candidates):
        return TargetDecision(
            "ADDRESS_NEEDS_REVIEW", reasons=("foreign_result",), candidates=candidates
        )
    if len(eligible) != 1:
        return TargetDecision(
            "ADDRESS_NEEDS_REVIEW",
            reasons=("competing_candidates" if len(eligible) > 1 else "no_eligible_target",),
            candidates=candidates,
        )
    selected = eligible[0]
    chosen = candidates[selected]
    # Competing address-level results cannot be ignored merely due to a weaker
    # component score. Number disagreement with such an alternative needs review.
    rivals = [
        i
        for i, v in enumerate(candidates)
        if i != selected and v["quality"] and all(v["component_matches"].values())
    ]
    if rivals:
        return TargetDecision(
            "ADDRESS_NEEDS_REVIEW", reasons=("competing_candidates",), candidates=candidates
        )
    approximate = chosen["quality"] == "approximate_address"
    classification = "GPS_TARGET_ELIGIBLE_WITH_CAUTION" if approximate else "GPS_TARGET_ELIGIBLE"
    if chosen["number_mismatch"]:
        classification = "GPS_TARGET_ELIGIBLE_WITH_NUMBER_WARNING"
    return TargetDecision(
        classification,
        chosen["quality"],
        150 if approximate else 100,
        selected,
        tuple(chosen["warnings"]),
        candidates=candidates,
    )
