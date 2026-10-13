"""Synthetic provider fixtures only; no live reverse-geocode requests."""

import json
from copy import deepcopy
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from app.models.permanent_address import PermanentAddressSession
from app.models.trust_score_snapshot import TrustScoreSnapshot
from app.services.permanent_address_geocoder import AmazonAddressGeocoder, TargetCipher
from app.services.permanent_address_onsite import area_decision, precise_area_decision
from tests.test_permanent_address_onsite import eligible, result
from tests.test_permanent_address_verification import ADDRESS, check, settings
from tests.test_permanent_address_verification import case as case


def decide(items):
    return precise_area_decision(ADDRESS.model_dump(), items)


@pytest.mark.parametrize("kind", ["PointAddress", "InterpolatedAddress"])
def test_supported_single_result_policy_parity(kind):
    item = result()
    item["PlaceType"] = kind
    current = decide([item])
    previous = area_decision(ADDRESS.model_dump(), [item])
    assert current["accepted"]
    assert all(current[key] == value for key, value in previous.items() if key != "diagnostics")
    assert current["diagnostics"]["selected_candidate_rank"] == 1


@pytest.mark.parametrize(
    "kind", [None, "Street", "Locality", "PointOfInterest", "Intersection", "SecondaryAddress"]
)
def test_no_precise_results_no_broad_fallback(kind, monkeypatch):
    item = result()
    item["PlaceType"] = kind
    original = area_decision
    calls = []

    def observed(claimed, items):
        calls.append(items)
        return original(claimed, items)

    monkeypatch.setattr("app.services.permanent_address_onsite.area_decision", observed)
    decision = decide([item] if kind else [])
    assert decision["reason"] == "no_supported_precision_result"
    assert not decision["accepted"]
    assert decision["diagnostics"]["precise_candidate_count"] == 0
    assert decision["diagnostics"]["evaluated_candidate_count"] == 0
    assert decision["diagnostics"]["selected_candidate_rank"] is None
    assert calls == [[]]


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("PostalCode", "302021", "pin_mismatch"),
        ("Street", "Different Road", "street_conflict"),
        ("Country", {"Code3": "USA"}, "country_mismatch"),
        ("Region", {"Code": "KA"}, "state_mismatch"),
        ("Locality", "Delhi", "city_mismatch"),
        ("AddressNumber", "999", "address_number_conflict"),
    ],
)
def test_first_failure_second_pass_unchanged_rules(field, value, reason):
    first = result()
    first["Address"][field] = value
    decision = decide([first, result(), result()])
    diagnostics = decision["diagnostics"]
    assert decision["accepted"]
    assert diagnostics["selected_candidate_rank"] == 2
    assert diagnostics["precise_candidate_count"] == 3
    assert diagnostics["evaluated_candidate_count"] == 2
    assert diagnostics["candidate_evaluations"][0]["reason"] == reason
    single = decide([first])
    previous = area_decision(ADDRESS.model_dump(), [first])
    assert all(single[k] == v for k, v in previous.items() if k != "diagnostics")


def test_all_precise_fail_no_least_bad_choice():
    first, second = result(), result()
    first["Address"]["PostalCode"] = "302099"
    second["Address"]["Street"] = "Unrelated Street"
    outcome = decide([first, second])
    assert not outcome["accepted"]
    data = outcome["diagnostics"]
    assert data["selected_candidate_rank"] is None
    assert data["evaluated_candidate_count"] == data["precise_candidate_count"] == 2
    assert [v["reason"] for v in data["candidate_evaluations"]] == [
        "pin_mismatch",
        "street_conflict",
    ]


@pytest.mark.parametrize("kind", ["PointAddress", "InterpolatedAddress"])
def test_estimated_precise_candidate_rejected(kind):
    first = result()
    first.update(PlaceType=kind, EstimatedPointAddress=True)
    rejected = decide([first])
    assert not rejected["accepted"]
    assert (
        rejected["diagnostics"]["candidate_evaluations"][0]["reverse_estimated_point_address"]
        is True
    )
    assert decide([first, result()])["diagnostics"]["selected_candidate_rank"] == 2


def test_provider_order_preserved_no_reranking_and_stop_at_first_pass():
    broad, first, later = result(), result(), result()
    broad["PlaceType"] = "Street"
    first.update(PlaceType="InterpolatedAddress", Distance=70)
    later.update(PlaceType="PointAddress", Distance=1)
    before = deepcopy([broad, first, later])
    data = decide([broad, first, later])["diagnostics"]
    assert data["selected_candidate_rank"] == 2
    assert data["reverse_place_type"] == "InterpolatedAddress"
    assert data["evaluated_candidate_count"] == 1
    assert [broad, first, later] == before


def test_bounded_results_never_consider_sixth_candidate():
    bad = result()
    bad["EstimatedPointAddress"] = True
    data = decide([bad] * 5 + [result()])["diagnostics"]
    assert data["bounded_result_count"] == data["precise_candidate_count"] == 5
    assert data["evaluated_candidate_count"] == len(data["candidate_evaluations"]) == 5
    assert data["selected_candidate_rank"] is None


def test_diagnostics_no_raw_data_or_unbounded_provider_fields():
    item = result()
    item.update(Title="PRIVATE_TITLE", PlaceId="PRIVATE_ID", Position=[12.3456789, 76.5432198])
    item["Address"].update(Street="PRIVATE_STREET", AddressNumber="PRIVATE_NUMBER")
    text = json.dumps(decide([item] * 7))
    for forbidden in (
        "PRIVATE_",
        "12.3456789",
        "76.5432198",
        "302020",
        "Jaipur",
        "Rajasthan",
        "Position",
        "Title",
    ):
        assert forbidden not in text


async def test_adapter_uses_ordered_precise_evaluation_once(monkeypatch):
    first = result()
    first["Address"]["PostalCode"] = "302099"
    request = Mock(return_value={"ResultItems": [first, result()]})
    monkeypatch.setattr(AmazonAddressGeocoder, "_reverse_request", request)
    outcome = await AmazonAddressGeocoder().confirm_area(ADDRESS.model_dump(), (0, 0))
    assert outcome["accepted"] and outcome["diagnostics"]["selected_candidate_rank"] == 2
    request.assert_called_once_with((0, 0))


@pytest.mark.parametrize("passes", [True, False])
async def test_durable_diagnostics_history_score_target_and_api_privacy(case, passes):
    db, users, _, _, geo = case
    row = await eligible(case)
    old_target = row.target_encrypted
    history = []
    for index in range(2):
        old = PermanentAddressSession(
            address_version_id=row.id,
            cycle=1,
            challenge_hash=f"history-{index}",
            started_at=row.created_at,
            expires_at=row.created_at,
            completed_at=row.created_at,
            result="NEEDS_REVIEW",
            derived_evidence={"onsite_confirmation": {"accepted": False}},
        )
        db.add(old)
        history.append(old)
    await db.flush()
    old_values = [(v.id, deepcopy(v.derived_evidence)) for v in history]
    score_query = select(TrustScoreSnapshot).where(TrustScoreSnapshot.user_id == users[0].id)
    scores_before = list((await db.scalars(score_query)).all())
    first, second = result(), result()
    first["Address"]["PostalCode"] = "302099"
    second["EstimatedPointAddress"] = not passes
    second["Position"] = [12.3456789, 76.5432198]
    decision = decide([first, second])
    geo.confirm_area.return_value = decision
    state, challenge, _ = await check(case, row.id)
    saved = await db.get(PermanentAddressSession, challenge.session_id)
    assert saved.derived_evidence["onsite_confirmation"]["diagnostics"] == decision["diagnostics"]
    for ident, data in old_values:
        assert (await db.get(PermanentAddressSession, ident)).derived_evidence == data
    assert list((await db.scalars(score_query)).all()) == scores_before
    assert state.successful_gps_checks == int(passes)
    assert state.document_status == "REQUIRED"
    assert "candidate_evaluations" not in state.model_dump_json()
    assert "diagnostics" not in state.model_dump_json()
    if passes:
        assert row.target_source == "onsite_confirmation" and row.target_confirmed_at
        assert TargetCipher(settings()).decrypt(
            row.target_encrypted, row.target_key_id, users[0].id, row.id
        ) == {"position": [0.0, 0.0]}
    else:
        assert state.status == "NEEDS_REVIEW" and row.target_encrypted == old_target
