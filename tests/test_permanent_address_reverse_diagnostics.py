"""Diagnostics privacy and decision parity against the frozen API245 algorithm."""

import json
import re
from copy import deepcopy
from itertools import product

import pytest
from sqlalchemy import select

from app.models.permanent_address import PermanentAddressSession
from app.models.trust_score_snapshot import TrustScoreSnapshot
from app.services.permanent_address_onsite import area_decision
from app.services.permanent_address_quality import (
    _CITY_ALIASES,
    _REGIONS,
    _region,
    normalize,
    street_normalize,
)
from tests.test_permanent_address_onsite import eligible, result
from tests.test_permanent_address_verification import ADDRESS, check
from tests.test_permanent_address_verification import case as case


# Frozen cde730c decision oracle: diagnostics must not change any existing field.
def _legacy_decision(claimed, items):
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


@pytest.mark.parametrize(
    "kind,estimated,reason",
    [
        ("PointAddress", False, "supported"),
        ("InterpolatedAddress", False, "supported"),
        ("Street", False, "unsupported_place_type"),
        ("PointAddress", True, "estimated_point_address"),
        ("Street", True, "unsupported_place_type_and_estimated"),
    ],
)
def test_precision_branches(kind, estimated, reason):
    item = result()
    item.update(PlaceType=kind, EstimatedPointAddress=estimated)
    data = area_decision(ADDRESS.model_dump(), [item])["diagnostics"]
    assert data["reverse_result_present"] and data["reverse_result_count"] == 1
    assert data["reverse_place_type"] == kind
    assert data["reverse_estimated_point_address"] is estimated
    assert data["reverse_precision_decision_reason"] == reason
    assert data["reverse_precision_supported"] == (reason == "supported")


@pytest.mark.parametrize(
    "street,line2,expected,line1_match,line2_match",
    [
        (None, None, "street_unavailable", False, False),
        ("  ", None, "street_unavailable", False, False),
        ("Synthetic Rd.", None, "street_exact_normalized_phrase_match", True, False),
        ("Other St.", "Near Other Street", "street_exact_normalized_phrase_match", False, True),
        (
            "Different Road",
            None,
            "street_text_present_but_no_contiguous_phrase_match",
            False,
            False,
        ),
        (
            "Synthetic Roadway",
            None,
            "street_text_present_but_no_contiguous_phrase_match",
            False,
            False,
        ),
    ],
)
def test_street_flags(street, line2, expected, line1_match, line2_match):
    claimed = ADDRESS.model_dump()
    claimed["address_line_2"] = line2
    item = result()
    item["Address"]["Street"] = street
    data = area_decision(claimed, [item])["diagnostics"]
    assert data["street_decision_reason"] == expected
    assert data["street_phrase_match_line1"] is line1_match
    assert data["street_phrase_match_line2"] is line2_match
    assert data["claimed_line1_normalized_nonempty"]
    assert data["claimed_line2_normalized_nonempty"] == bool(line2)
    assert data["provider_street_present"] == bool(street and street.strip())
    assert data["provider_street_normalized_nonempty"] == bool(street and street.strip())


@pytest.mark.parametrize(
    "number,expected", [(None, "unavailable"), ("123", "matched"), ("999", "conflict")]
)
def test_components_and_number(number, expected):
    item = result()
    item["Address"]["AddressNumber"] = number
    data = area_decision(ADDRESS.model_dump(), [item])["diagnostics"]
    for key in ("country", "state", "city", "postal_code"):
        assert data["provider_" + key + "_present"]
        assert data[key + "_match"]
    assert data["provider_address_number_present"] == bool(number)
    assert data["address_number_state"] == expected


@pytest.mark.parametrize(
    "field,value,flag",
    [
        ("Country", {"Code3": "USA"}, "country_match"),
        ("Region", {"Code": "KA"}, "state_match"),
        ("Locality", "Other City", "city_match"),
        ("PostalCode", "302021", "postal_code_match"),
    ],
)
def test_component_mismatches(field, value, flag):
    item = result()
    item["Address"][field] = value
    assert area_decision(ADDRESS.model_dump(), [item])["diagnostics"][flag] is False


def test_empty_unknown_and_malformed_flags_are_safe():
    empty = area_decision(ADDRESS.model_dump(), [])["diagnostics"]
    assert not empty["reverse_result_present"] and empty["reverse_result_count"] == 0
    assert empty["reverse_precision_decision_reason"] == "no_result"
    assert empty["country_match"] is None
    item = result()
    item.update(PlaceType="PRIVATE_TYPE_SENTINEL", EstimatedPointAddress="PRIVATE_FLAG_SENTINEL")
    decision = area_decision(ADDRESS.model_dump(), [item])
    data = decision["diagnostics"]
    assert data["reverse_place_type"] == "other"
    assert data["reverse_estimated_point_address"] is None
    assert not data["reverse_estimated_point_address_valid"]
    assert "PRIVATE_" not in json.dumps(decision)
    del item["PlaceType"]
    del item["EstimatedPointAddress"]
    assert (
        area_decision(ADDRESS.model_dump(), [item])["diagnostics"]["reverse_place_type"]
        == "missing"
    )


def test_no_text_coordinates_or_raw_provider_payload_retained():
    claimed = ADDRESS.model_dump()
    claimed["address_line_2"] = "PRIVATE_CLAIMED_SENTINEL"
    item = result()
    item.update(
        Title="PRIVATE_TITLE_SENTINEL",
        Position=[12.3456789, 76.5432198],
        PlaceId="PRIVATE_ID_SENTINEL",
        Extra={"raw": "PRIVATE_RAW_SENTINEL"},
    )
    item["Address"].update(
        Street="PRIVATE_STREET_SENTINEL",
        Label="PRIVATE_LABEL_SENTINEL",
        AddressNumber="PRIVATE_NUMBER_SENTINEL",
    )
    decision = area_decision(claimed, [item])
    encoded = json.dumps(decision)
    for forbidden in ("PRIVATE_", "12.3456789", "76.5432198", "302020", "Jaipur", "Rajasthan"):
        assert forbidden not in encoded
    assert all(type(v) in (str, bool, int, type(None)) for v in decision["diagnostics"].values())


def test_decisions_identical_to_api245():
    claimed = ADDRESS.model_dump()
    for kind, estimated, street, country in product(
        ("PointAddress", "InterpolatedAddress", "Street", "SecondaryAddress", None),
        (None, False, True, "invalid"),
        (None, "", "Synthetic Rd", "Different Road", 123),
        ("IN", "USA"),
    ):
        item = result()
        item.update(PlaceType=kind, EstimatedPointAddress=estimated)
        item["Address"].update(Street=street, Country={"Code2": country})
        before = deepcopy(item)
        current = area_decision(claimed, [item])
        current.pop("diagnostics")
        assert current == _legacy_decision(claimed, [item])
        assert item == before
    current = area_decision(claimed, [])
    current.pop("diagnostics")
    assert current == _legacy_decision(claimed, [])


@pytest.mark.parametrize("kind", ["PointAddress", "Street"])
async def test_durable_diagnostics_internal_only_and_history_unchanged(case, kind):
    db, users, svc, _, geo = case
    row = await eligible(case)
    historical = PermanentAddressSession(
        address_version_id=row.id,
        cycle=1,
        challenge_hash="historical-test",
        started_at=row.created_at,
        expires_at=row.created_at,
        completed_at=row.created_at,
        result="NEEDS_REVIEW",
        derived_evidence={
            "onsite_confirmation": {
                "accepted": False,
                "reason": "unsupported_precision",
                "street_status": "conflict",
            }
        },
    )
    db.add(historical)
    await db.flush()
    historical_id = historical.id
    score_query = (
        select(TrustScoreSnapshot.id, TrustScoreSnapshot.overall_score)
        .where(TrustScoreSnapshot.user_id == users[0].id)
        .order_by(TrustScoreSnapshot.id)
    )
    scores_before = list((await db.execute(score_query)).all())
    old_audit = deepcopy(historical.derived_evidence)
    item = result()
    item["PlaceType"] = kind
    decision = area_decision(ADDRESS.model_dump(), [item])
    geo.confirm_area.return_value = decision
    state, challenge, _ = await check(case, row.id)
    db.expire_all()
    saved = await db.get(PermanentAddressSession, challenge.session_id)
    assert saved.derived_evidence["onsite_confirmation"]["diagnostics"] == decision["diagnostics"]
    old = await db.get(PermanentAddressSession, historical_id)
    assert old.derived_evidence == old_audit
    assert list((await db.execute(score_query)).all()) == scores_before
    assert "diagnostics" not in state.model_dump_json()
    assert "reverse_place_type" not in state.model_dump_json()
    assert state.successful_gps_checks == (1 if kind == "PointAddress" else 0)
