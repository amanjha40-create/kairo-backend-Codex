import json
from copy import deepcopy
from dataclasses import asdict

import pytest

from app.services.permanent_address_quality import evaluate_targets

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


def test_missing_street_blocks_even_for_point_address():
    item = deepcopy(ITEM)
    del item["Address"]["Street"]
    assert not evaluate_targets([item], QUERY).eligible


def test_truncated_candidate_set_fails_closed():
    assert evaluate_targets([ITEM], QUERY, max_results=1).reasons == ("candidate_list_truncated",)


def test_empty_results_require_review():
    assert not evaluate_targets([], QUERY).eligible
