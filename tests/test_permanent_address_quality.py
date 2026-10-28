import json
from copy import deepcopy
from dataclasses import asdict

import pytest

from app.services.permanent_address_quality import (
    STREET_UNAVAILABLE_QUALITY,
    evaluate_targets,
    street_reconciles,
)

QUERY = {
    "Country": "IND",
    "Region": "Rajasthan",
    "Locality": "Jaipur",
    "PostalCode": "302020",
    "Street": "Synthetic Road",
    "AddressNumber": "123",
}
ITEM = {
    "PlaceType": "PointAddress",
    "Position": [0.0, 0.0],
    "Address": {
        "Country": {"Code3": "IND"},
        "Region": {"Name": "Rajasthan"},
        "Locality": "Jaipur",
        "PostalCode": "302020",
        "Street": "Synthetic Road",
        "AddressNumber": "123",
    },
    "MatchScores": {
        "Overall": 0.89,
        "Components": {
            "Address": {
                "Country": 1,
                "Region": 1,
                "Locality": 1,
                "PostalCode": 1,
                "AddressNumber": 1,
            }
        },
    },
}


@pytest.mark.parametrize(
    ("claimed", "provider"),
    [
        ("Building 8, Alpha Beta, Enclave", "Alpha Beta Road"),
        ("Building 8, Alpha Beta Road, Enclave", "Alpha Beta Rd"),
    ],
)
def test_street_reconciliation_accepts_exact_core_with_terminal_designator(claimed, provider):
    assert street_reconciles(claimed, provider)


@pytest.mark.parametrize(
    ("claimed", "provider"),
    [
        ("Building 8, Alpha, Enclave", "Alpha Beta Road"),
        ("Building 8, Enclave", "Alpha Beta Road"),
        ("Building 8, Alpha Beta, Enclave", "Alpha Beta Extension"),
        ("Building 8, Alpha Beta, Enclave", "Alpha Road Beta"),
        ("Building 8, Beta Alpha, Enclave", "Alpha Beta Road"),
        ("Building 8, Alpha, Enclave", "Alpha Road"),
        ("Building 8, Ab Cd, Enclave", "Ab Cd Road"),
        ("Road Building 8, Alpha Beta, Enclave", "Alpha Beta Road"),
    ],
)
def test_street_reconciliation_rejects_unsafe_designator_omissions(claimed, provider):
    assert not street_reconciles(claimed, provider)


@pytest.mark.parametrize("overall", [0.0, 0.89, 0.95, 1.0, None])
def test_overall_does_not_decide_target(overall):
    item = deepcopy(ITEM)
    item["MatchScores"]["Overall"] = overall
    result = evaluate_targets([item], QUERY)
    assert result.eligible and result.radius_m == 100


@pytest.mark.parametrize(
    "field,value",
    [
        ("PostalCode", "400051"),
        ("Locality", "Mumbai"),
        ("Region", {"Name": "Maharashtra"}),
        ("Country", {"Code3": "USA"}),
        ("Street", "Different Road"),
    ],
)
def test_conflict_blocks_despite_perfect_scores(field, value):
    item = deepcopy(ITEM)
    item["Address"][field] = value
    item["MatchScores"]["Overall"] = 1
    assert not evaluate_targets([item], QUERY).eligible


def test_number_only_warning_does_not_correct_claim():
    item = deepcopy(ITEM)
    item["Address"]["AddressNumber"] = "124"
    item["MatchScores"]["Components"]["Address"]["AddressNumber"] = 0
    claimed = deepcopy(QUERY)
    result = evaluate_targets([item], claimed)
    assert result.classification == "GPS_TARGET_ELIGIBLE_WITH_NUMBER_WARNING"
    assert result.warnings == ("address_number_mismatch",)
    assert claimed == QUERY


@pytest.mark.parametrize(
    "field,value",
    [
        ("PostalCode", "400051"),
        ("Locality", "Mumbai"),
        ("Region", {"Name": "Maharashtra"}),
        ("Street", "Different Road"),
    ],
)
def test_number_warning_with_conflict_blocks(field, value):
    item = deepcopy(ITEM)
    item["Address"]["AddressNumber"] = "124"
    item["Address"][field] = value
    assert not evaluate_targets([item], QUERY).eligible


def test_competing_address_results_block_regardless_of_overall():
    second = deepcopy(ITEM)
    second["Address"]["AddressNumber"] = "124"
    second["Position"] = [0.01, 0.01]
    second["MatchScores"]["Overall"] = 0.1
    assert evaluate_targets([ITEM, second], QUERY).reasons == ("competing_candidates",)


@pytest.mark.parametrize(
    "place_type",
    [
        "Country",
        "Region",
        "Locality",
        "District",
        "PostalCode",
        "Street",
        "PointOfInterest",
        "SecondaryAddress",
        "Unknown",
    ],
)
def test_broad_and_unqualified_types_block(place_type):
    item = deepcopy(ITEM)
    item["PlaceType"] = place_type
    assert not evaluate_targets([item], QUERY).eligible


def test_interpolated_tier_is_capped():
    item = deepcopy(ITEM)
    item["PlaceType"] = "InterpolatedAddress"
    result = evaluate_targets([item], QUERY)
    assert result.eligible and result.quality == "approximate_address"
    assert result.radius_m == 150


def test_estimated_point_does_not_silently_become_tier_a():
    item = deepcopy(ITEM)
    item["EstimatedPointAddress"] = True
    assert not evaluate_targets([item], QUERY).eligible


@pytest.mark.parametrize(
    "position", [[181, 0], [0, 91], [float("nan"), 0], [float("inf"), 0], [True, False], [0], []]
)
def test_invalid_coordinates_block(position):
    item = deepcopy(ITEM)
    item["Position"] = position
    assert not evaluate_targets([item], QUERY).eligible


def test_street_score_not_invented_and_abbreviation_normalized():
    query = dict(QUERY, Street="Synthetic Rd.")
    result = evaluate_targets([ITEM], query)
    assert result.eligible
    assert result.candidates[0]["street_score_available"] is False
    assert "Street" not in result.candidates[0]["component_scores"]


def test_exact_components_do_not_need_numeric_cutoff():
    item = deepcopy(ITEM)
    item["MatchScores"]["Components"]["Address"]["Locality"] = 0.89
    assert evaluate_targets([item], QUERY).eligible


def test_foreign_alternative_fails_closed():
    foreign = deepcopy(ITEM)
    foreign["Address"]["Country"] = {"Code3": "USA"}
    assert evaluate_targets([ITEM, foreign], QUERY).reasons == ("foreign_result",)


def test_safe_decision_does_not_expose_infrastructure():
    output = json.dumps(asdict(evaluate_targets([ITEM], QUERY)))
    for forbidden in ("302020", "Synthetic Road", "Jaipur", "Position", "latitude", "longitude"):
        assert forbidden not in output


def test_missing_street_point_address_has_truthful_fallback():
    item = deepcopy(ITEM)
    del item["Address"]["Street"]
    before = deepcopy(item)
    result = evaluate_targets([item], QUERY)
    assert result.eligible
    assert result.classification == "GPS_TARGET_ELIGIBLE_STREET_UNAVAILABLE"
    assert result.quality == STREET_UNAVAILABLE_QUALITY and result.radius_m == 75
    assert result.street_status == "provider_unavailable"
    assert result.candidates[0]["component_matches"]["street"] is False
    assert result.warnings == ("provider_street_unavailable",)
    assert item == before


def test_truncated_candidate_set_fails_closed():
    assert evaluate_targets([ITEM], QUERY, max_results=1).reasons == ("candidate_list_truncated",)


def test_empty_results_require_review():
    assert not evaluate_targets([], QUERY).eligible


def missing_street():
    item = deepcopy(ITEM)
    del item["Address"]["Street"]
    return item


@pytest.mark.parametrize("field,value", [
    ("Street", "Conflicting Road"), ("PostalCode", "400051"),
    ("Region", {"Name": "Maharashtra"}), ("Locality", "Mumbai"),
    ("Country", {"Code3": "USA"}), ("Country", {"Code3": "IND", "Code2": "US"}),
    ("AddressNumber", "999"), ("Street", 123), ("Street", "!!!"),
])
def test_fallback_never_waives_component_conflicts(field, value):
    item = missing_street()
    item["Address"][field] = value
    assert not evaluate_targets([item], QUERY).eligible


@pytest.mark.parametrize("field", ["Region", "Locality", "Street", "Country"])
def test_fallback_requires_claimed_structure(field):
    query = dict(QUERY)
    query.pop(field)
    assert not evaluate_targets([missing_street()], query).eligible


@pytest.mark.parametrize("place_type", [
    "InterpolatedAddress", "Street", "PostalCode", "Locality", "District", "Region",
    "Country", "PointOfInterest", "SecondaryAddress", "InferredSecondaryAddress",
])
def test_missing_street_fallback_is_point_address_only(place_type):
    item = missing_street()
    item["PlaceType"] = place_type
    assert not evaluate_targets([item], QUERY).eligible


@pytest.mark.parametrize("position", [None, [], [0], [181, 0], [True, False], [float("nan"), 0]])
def test_missing_street_cannot_qualify_without_real_usable_position(position):
    item = missing_street()
    item["Position"] = position
    assert not evaluate_targets([item], QUERY).eligible


def test_estimated_point_cannot_use_fallback():
    item = missing_street()
    item["EstimatedPointAddress"] = True
    assert not evaluate_targets([item], QUERY).eligible


@pytest.mark.parametrize("other_street", [None, "Synthetic Road", "Conflicting Road"])
def test_comparable_point_competitors_block_fallback(other_street):
    other = missing_street()
    other["Address"]["Street"] = other_street
    other["Position"] = [0.01, 0.01]
    other["MatchScores"]["Overall"] = 0.01
    assert evaluate_targets([missing_street(), other], QUERY).reasons == ("competing_candidates",)


@pytest.mark.parametrize("overall", [0.0, 0.41, 0.9, 1.0, None])
def test_fallback_has_no_overall_threshold(overall):
    item = missing_street()
    item["MatchScores"]["Overall"] = overall
    assert evaluate_targets([item], QUERY).eligible


@pytest.mark.parametrize("radius", [0, -1, 76, float("nan"), float("inf")])
def test_fallback_radius_cannot_be_enlarged(radius):
    with pytest.raises(ValueError):
        evaluate_targets([missing_street()], QUERY, street_unavailable_radius_m=radius)


def test_fallback_smaller_radius_and_no_number_inference():
    query = dict(QUERY)
    query.pop("AddressNumber")
    result = evaluate_targets([missing_street()], query, street_unavailable_radius_m=60)
    assert result.eligible and result.radius_m == 60
    assert result.candidates[0]["number_mismatch"] is False
    output = json.dumps(asdict(result))
    for forbidden in ("302020", "Synthetic Road", "Jaipur", "Position", "latitude", "longitude"):
        assert forbidden not in output
