"""India area agreement only; no provider address or coordinates in decisions."""

import re

from app.services.permanent_address_quality import (
    _CITY_ALIASES,
    _REGIONS,
    _region,
    normalize,
    street_normalize,
)


def area_decision(claimed, items):
    # Use the closest result, never search for a more convenient matching address.
    if not items:
        return {"accepted": False, "reason": "no_result"}
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
