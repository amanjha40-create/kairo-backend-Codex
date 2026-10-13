"""India area agreement only; no provider address or coordinates in decisions."""

import re

from app.services.permanent_address_quality import (
    _CITY_ALIASES,
    _REGIONS,
    _region,
    normalize,
    street_normalize,
)

_REVERSE_PLACE_TYPES = frozenset(
    {
        "Locality",
        "Intersection",
        "Street",
        "PointAddress",
        "InterpolatedAddress",
        "SecondaryAddress",
        "PointOfInterest",
    }
)


def _diagnostics(claimed, items, checks=None, street="unavailable", number="unavailable"):
    """Internal flags only; never retain provider strings or location values."""
    item = items[0] if items else {}
    address = item.get("Address") or {}
    place_type = item.get("PlaceType")
    estimated = item.get("EstimatedPointAddress")
    supported_type = place_type in {"PointAddress", "InterpolatedAddress"}
    estimated_rejected = bool(item.get("EstimatedPointAddress", False))
    if not items:
        precision_reason = "no_result"
    elif not supported_type and estimated_rejected:
        precision_reason = "unsupported_place_type_and_estimated"
    elif not supported_type:
        precision_reason = "unsupported_place_type"
    elif estimated_rejected:
        precision_reason = "estimated_point_address"
    else:
        precision_reason = "supported"
    raw_street = address.get("Street")
    normalized_street = street_normalize(raw_street)
    lines = [street_normalize(claimed.get(k)) for k in ("address_line_1", "address_line_2")]
    matches = [
        bool(
            isinstance(raw_street, str)
            and normalized_street
            and f" {normalized_street} " in f" {line} "
        )
        for line in lines
    ]
    checks = checks or {}
    return {
        "reverse_result_present": bool(items),
        "reverse_result_count": len(items),
        "reverse_place_type": (
            place_type
            if isinstance(place_type, str) and place_type in _REVERSE_PLACE_TYPES
            else "missing"
            if place_type is None
            else "other"
        ),
        "reverse_estimated_point_address": estimated if type(estimated) is bool else None,
        "reverse_estimated_point_address_valid": estimated is None or type(estimated) is bool,
        "reverse_precision_supported": bool(items) and supported_type and not estimated_rejected,
        "reverse_precision_decision_reason": precision_reason,
        **{
            "provider_" + label + "_present": bool(address.get(field))
            for label, field in (
                ("country", "Country"),
                ("state", "Region"),
                ("city", "Locality"),
                ("postal_code", "PostalCode"),
                ("address_number", "AddressNumber"),
            )
        },
        "provider_street_present": raw_street is not None
        and not (isinstance(raw_street, str) and not raw_street.strip()),
        "country_match": checks.get("country"),
        "state_match": checks.get("state"),
        "city_match": checks.get("city"),
        "postal_code_match": checks.get("pin"),
        "street_match": street == "matched",
        "address_number_state": number,
        "claimed_line1_normalized_nonempty": bool(lines[0]),
        "claimed_line2_normalized_nonempty": bool(lines[1]),
        "provider_street_normalized_nonempty": bool(normalized_street),
        "street_phrase_match_line1": matches[0],
        "street_phrase_match_line2": matches[1],
        "street_decision_reason": {
            "unavailable": "street_unavailable",
            "matched": "street_exact_normalized_phrase_match",
            "conflict": "street_text_present_but_no_contiguous_phrase_match",
        }[street],
    }


def area_decision(claimed, items):
    # Use the closest result, never search for a more convenient matching address.
    if not items:
        return {
            "accepted": False,
            "reason": "no_result",
            "diagnostics": _diagnostics(claimed, items),
        }
    item = items[0]
    address = item.get("Address") or {}
    country = address.get("Country") or {}
    region = address.get("Region") or {}
    checks = {
        "country": claimed.get("country") == "IN"
        and (country.get("Code2") == "IN" or country.get("Code3") == "IND")
        and country.get("Code2") in (None, "", "IN")
        and country.get("Code3") in (None, "", "IND"),
        "state": bool(claimed.get("state"))
        and _region(claimed["state"])
        in {
            _region(region.get("Name")),
            _region(region.get("Code")),
        },
    }
    known_regions = {_region(region.get("Name")), _region(region.get("Code"))} & set(
        _REGIONS.values()
    )
    if any(value != _region(claimed.get("state")) for value in known_regions):
        checks["state"] = False
    expected, returned = normalize(claimed.get("city")), normalize(address.get("Locality"))
    checks["city"] = bool(expected and returned) and _CITY_ALIASES.get(
        expected, expected
    ) == _CITY_ALIASES.get(returned, returned)
    raw_pin = address.get("PostalCode")
    pin_missing = raw_pin is None or (isinstance(raw_pin, str) and not raw_pin.strip())
    checks["pin"] = pin_missing or (
        isinstance(raw_pin, str)
        and bool(re.fullmatch(r"[1-9][0-9]{5}", raw_pin.strip()))
        and raw_pin.strip() == claimed.get("postal_code")
    )
    raw_street = address.get("Street")
    street_missing = raw_street is None or (isinstance(raw_street, str) and not raw_street.strip())
    returned_street = street_normalize(raw_street)
    lines = [street_normalize(claimed.get(k)) for k in ("address_line_1", "address_line_2")]
    street = (
        "unavailable"
        if street_missing
        else (
            "matched"
            if isinstance(raw_street, str)
            and returned_street
            and any(f" {returned_street} " in f" {line} " for line in lines)
            else "conflict"
        )
    )
    # Only an explicit leading house-number token is comparable; do not guess units.
    number = re.match(
        r"^\s*(\d+[a-zA-Z]?(?:[-/]\d+[a-zA-Z]?)?)(?=\s|,|$)", claimed.get("address_line_1", "")
    )
    returned_number = normalize(address.get("AddressNumber"))
    number_status = (
        "unavailable"
        if not number or not returned_number
        else ("matched" if normalize(number[1]) == returned_number else "conflict")
    )
    precision = item.get("PlaceType") in {"PointAddress", "InterpolatedAddress"} and not item.get(
        "EstimatedPointAddress", False
    )
    reasons = [f"{key}_mismatch" for key, matched in checks.items() if not matched]
    if not precision:
        reasons.append("unsupported_precision")
    if street == "conflict":
        reasons.append("street_conflict")
    if number_status == "conflict":
        reasons.append("address_number_conflict")
    return {
        "accepted": not reasons,
        "reason": reasons[0] if reasons else "area_match",
        "component_matches": checks,
        "pin_supplied": not pin_missing,
        "street_status": street,
        "number_status": number_status,
        "policy": "india-onsite-v1",
        "diagnostics": _diagnostics(claimed, items, checks, street, number_status),
    }


def ambiguous_area_valid(metadata):
    """Only address-level ambiguity with independently agreeing structure qualifies."""
    if not set(metadata.get("reasons", [])) & {"competing_candidates", "competing_address_target"}:
        return False
    candidates = metadata.get("candidates") or []
    return len(candidates) > 1 and all(
        candidate.get("position_usable")
        and candidate.get("quality")
        and all(
            candidate.get("component_matches", {}).get(key)
            for key in ("country", "state", "city", "pin")
        )
        and not candidate.get("number_mismatch")
        and candidate.get("street_status") in {"matched", "provider_unavailable"}
        and not candidate.get("reasons")
        for candidate in candidates
    )
