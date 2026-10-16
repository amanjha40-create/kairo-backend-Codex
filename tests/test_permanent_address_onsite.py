import json
from copy import deepcopy
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from app.exceptions import ConflictError, NotFoundError, ServiceUnavailableError
from app.models.permanent_address import PermanentAddressSession as Session
from app.models.permanent_address import PermanentAddressVersion as Version
from app.schemas.permanent_address import AddressReviewInput, LocationCompleteInput
from app.services.permanent_address_geocoder import AmazonAddressGeocoder, TargetCipher
from app.services.permanent_address_onsite import area_decision
from app.services.permanent_address_policy import assess_location_batch
from tests.test_permanent_address_verification import (
    ADDRESS,
    NOW,
    check,
    evidence,
    prepare,
    samples,
    settings,
)
from tests.test_permanent_address_verification import case as case


def result():
    return {
        "PlaceType": "PointAddress",
        "Address": {
            "Country": {"Code2": "IN", "Code3": "IND"},
            "Region": {"Name": "Rajasthan", "Code": "RJ"},
            "Locality": "Jaipur",
            "PostalCode": "302020",
        },
    }


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("Country", {"Code3": "USA"}, "country_mismatch"),
        ("Region", {"Code": "KA"}, "state_mismatch"),
        ("Locality", "Delhi", "city_mismatch"),
        ("PostalCode", "302021", "pin_mismatch"),
        ("Street", "Different Road", "street_conflict"),
        ("AddressNumber", "999", "address_number_conflict"),
    ],
)
def test_component_conflicts(field, value, reason):
    item = result()
    item["Address"][field] = value
    decision = area_decision(ADDRESS.model_dump(), [item])
    assert not decision["accepted"] and decision["reason"] == reason
    assert value not in decision.values()


@pytest.mark.parametrize("street", [None, "", "Synthetic Rd"])
@pytest.mark.parametrize("pin", [None, "302020"])
def test_missing_street_and_pin_policy(street, pin):
    item = result()
    item["Address"].update(Street=street, PostalCode=pin, AddressNumber="123")
    assert area_decision(ADDRESS.model_dump(), [item])["accepted"]


@pytest.mark.parametrize("kind", ["Locality", "PostalCode", "Street"])
def test_broad_target_blocked(kind):
    item = result()
    item["PlaceType"] = kind
    assert not area_decision(ADDRESS.model_dump(), [item])["accepted"]


def test_nearest_conflict_cannot_be_hidden_by_later_result():
    wrong = deepcopy(result())
    wrong["Address"]["PostalCode"] = "302099"
    assert not area_decision(ADDRESS.model_dump(), [wrong, result()])["accepted"]
    assert not area_decision(ADDRESS.model_dump(), [])["accepted"]


@pytest.mark.parametrize("kind", ["mock", "one", "stale", "poor", "unstable", "duplicates"])
def test_invalid_batch_never_has_representative(kind):
    values = samples(NOW)
    if kind == "mock":
        values[0].mock_location = True
    elif kind == "one":
        values = values[:1]
    elif kind == "stale":
        values[0].timestamp = NOW - timedelta(seconds=10)
    elif kind == "poor":
        values[0].accuracy_m = 51
    elif kind == "unstable":
        values[0].latitude = 1
    else:
        values[1].timestamp = values[0].timestamp
    _, representative = assess_location_batch(values, NOW, NOW + timedelta(seconds=33))
    assert representative is None


async def eligible(case):
    db, _, svc, _, geo = case
    version = await prepare(case)
    row = await db.get(Version, version)
    row.target_confirmation_reason = "reviewed_provider_discrepancy"
    row.target_status = "confirmation_required"
    geo.confirm_area = AsyncMock(return_value=area_decision(ADDRESS.model_dump(), [result()]))
    await db.flush()
    return row


async def test_enrollment_encrypted_lock_three_days_and_document(case):
    db, users, svc, clock, geo = case
    row = await eligible(case)
    old = row.target_encrypted
    state, challenge, payload = await check(case, row.id)
    assert state.successful_gps_checks == 1 and state.target_source == "onsite_confirmation"
    assert not state.target_confirmation_required and not state.can_start_location
    assert row.target_encrypted != old and row.target_confirmed_at
    assert row.geocode_metadata["provider_target_superseded"]
    assert TargetCipher(settings()).decrypt(
        row.target_encrypted, row.target_key_id, users[0].id, row.id
    ) == {"position": [0.0, 0.0]}
    locked = row.target_encrypted
    audit = (await db.get(Session, challenge.session_id)).derived_evidence
    for forbidden in ("latitude", "longitude", "position", "samples", "PostalCode", "302020"):
        assert forbidden not in json.dumps(audit)
    with pytest.raises(ConflictError):
        await svc.finish(users[0].id, challenge.session_id, payload)
    with pytest.raises(ConflictError):
        await svc.start(users[0].id, row.id)
    for day in (1, 2):
        clock[0] = NOW + timedelta(days=day)
        state, _, _ = await check(case, row.id)
        assert row.target_encrypted == locked
    assert geo.confirm_area.await_count == 1 and geo.calls == 1
    assert state.successful_gps_checks == 3 and state.status == "LOCATION_CONFIRMED"
    document = await evidence(case, row.id)
    await svc.review(
        users[2].id,
        row.id,
        AddressReviewInput(document_id=document.id, outcome="MATCH", observed_address=ADDRESS),
    )
    assert (await svc.state(users[0].id)).status == "PERMANENT_ADDRESS_VERIFIED"


async def test_fixed_target_outside_and_expired_cycle_do_not_recenter(case):
    db, users, svc, clock, geo = case
    row = await eligible(case)
    await check(case, row.id)
    locked = row.target_encrypted
    clock[0] = NOW + timedelta(days=1)
    challenge = await svc.start(users[0].id, row.id)
    values = samples(clock[0])
    for sample in values:
        sample.latitude = 0.00072  # ~80 m, outside 75 m but within old precise 100 m.
    clock[0] += timedelta(seconds=33)
    state = await svc.finish(
        users[0].id,
        challenge.session_id,
        LocationCompleteInput(challenge=challenge.challenge, samples=values),
    )
    assert state.last_location_result == "OUTSIDE_EXPECTED_AREA"
    assert state.successful_gps_checks == 1 and row.target_encrypted == locked
    clock[0] = NOW + timedelta(days=8)
    state, _, _ = await check(case, row.id)
    assert state.successful_gps_checks == 1 and row.target_encrypted == locked
    geo.confirm_area.assert_awaited_once()


@pytest.mark.parametrize("kind", ["mismatch", "unavailable", "interrupted"])
async def test_durable_reservation_prevents_provider_retry(case, kind):
    db, users, svc, clock, geo = case
    row = await eligible(case)
    original = row.target_encrypted
    if kind == "mismatch":
        geo.confirm_area.return_value = {"accepted": False, "reason": "pin_mismatch"}
    else:
        geo.confirm_area.side_effect = (
            ServiceUnavailableError()
            if kind == "unavailable"
            else RuntimeError("synthetic interrupted process")
        )
    if kind == "interrupted":
        with pytest.raises(RuntimeError):
            await check(case, row.id)
        state = await svc.state(users[0].id)
    else:
        state, _, _ = await check(case, row.id)
    assert row.target_encrypted == original and row.target_source != "onsite_confirmation"
    assert state.successful_gps_checks == 0 and state.status == "NEEDS_REVIEW"
    assert not state.can_start_location
    with pytest.raises(ConflictError):
        await svc.start(users[0].id, row.id)
    geo.confirm_area.assert_awaited_once()


async def test_invalid_batch_no_provider_and_cross_user(case):
    _, users, svc, clock, geo = case
    row = await eligible(case)
    with pytest.raises(NotFoundError):
        await svc.start(users[1].id, row.id)
    challenge = await svc.start(users[0].id, row.id)
    values = samples(clock[0], mock_location=True)
    clock[0] += timedelta(seconds=33)
    payload = LocationCompleteInput(challenge=challenge.challenge, samples=values)
    with pytest.raises(NotFoundError):
        await svc.finish(users[1].id, challenge.session_id, payload)
    state = await svc.finish(users[0].id, challenge.session_id, payload)
    assert state.successful_gps_checks == 0 and state.last_location_result == "NEEDS_REVIEW"
    assert state.status == "NEEDS_REVIEW" and not state.can_start_location
    geo.confirm_area.assert_not_awaited()


async def test_material_edit_requires_new_confirmation(case):
    _, users, svc, _, geo = case
    row = await eligible(case)
    await check(case, row.id)
    state = await svc.save_address(
        users[0].id, ADDRESS.model_copy(update={"address_line_1": "124 Synthetic Road"})
    )
    assert state.successful_gps_checks == 0 and state.target_confirmation_required
    assert state.target_source == "provider_geocode" and row.target_status == "superseded"
    geo.confirm_area.assert_awaited_once()


async def test_address_edit_during_provider_call_cannot_enroll_old_version(case):
    _, users, svc, _, geo = case
    row = await eligible(case)
    old = row.target_encrypted

    async def edit(*args):
        await svc.save_address(users[0].id, ADDRESS.model_copy(update={"city": "Different City"}))
        return {"accepted": True}

    geo.confirm_area.side_effect = edit
    with pytest.raises(NotFoundError):
        await check(case, row.id)
    assert row.target_encrypted == old and row.target_source != "onsite_confirmation"
    assert (await svc.state(users[0].id)).successful_gps_checks == 0


async def test_inflight_duplicate_completion_cannot_send_again(case):
    _, users, svc, clock, geo = case
    row = await eligible(case)
    challenge = await svc.start(users[0].id, row.id)
    payload = LocationCompleteInput(challenge=challenge.challenge, samples=samples(clock[0]))
    clock[0] += timedelta(seconds=33)

    async def duplicate(*args):
        with pytest.raises(ConflictError):
            await svc.finish(users[0].id, challenge.session_id, payload)
        return area_decision(ADDRESS.model_dump(), [result()])

    geo.confirm_area.side_effect = duplicate
    state = await svc.finish(users[0].id, challenge.session_id, payload)
    assert state.successful_gps_checks == 1
    geo.confirm_area.assert_awaited_once()


async def test_monthly_budget_blocks_reverse_before_network(case):
    _, _, svc, _, geo = case
    row = await eligible(case)
    svc.settings = svc.settings.model_copy(update={"permanent_address_monthly_geocode_limit": 1})
    state, _, _ = await check(case, row.id)
    assert state.successful_gps_checks == 0 and state.last_location_result == "NEEDS_REVIEW"
    geo.confirm_area.assert_not_awaited()


async def test_ordinary_outside_result_does_not_enable_reenrollment(case):
    db, users, svc, clock, geo = case
    version = await prepare(case)
    row = await db.get(Version, version)
    original = row.target_encrypted
    challenge = await svc.start(users[0].id, version)
    values = samples(clock[0])
    for sample in values:
        sample.latitude = 0.01
    clock[0] += timedelta(seconds=33)
    state = await svc.finish(
        users[0].id,
        challenge.session_id,
        LocationCompleteInput(challenge=challenge.challenge, samples=values),
    )
    assert state.last_location_result == "OUTSIDE_EXPECTED_AREA"
    assert not state.target_confirmation_required and row.target_encrypted == original


def test_city_alias_and_missing_structure_fail_closed():
    claimed = ADDRESS.model_dump()
    claimed.update(city="Bangalore", state="Karnataka")
    item = result()
    item["Address"].update(Locality="Bengaluru", Region={"Code": "IN-KA"})
    assert area_decision(claimed, [item])["accepted"]
    for field in ("Locality", "Region", "Country"):
        broken = deepcopy(item)
        broken["Address"].pop(field)
        assert not area_decision(claimed, [broken])["accepted"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("PostalCode", "???"),
        ("PostalCode", 302020),
        ("PostalCode", "302020!"),
        ("Street", "???"),
        ("Region", {"Code": "KA", "Name": "Rajasthan"}),
    ],
)
def test_malformed_or_contradictory_provider_components_fail_closed(field, value):
    item = result()
    item["Address"][field] = value
    assert not area_decision(ADDRESS.model_dump(), [item])["accepted"]


def test_provider_contract_one_send_no_forward_geocode(monkeypatch):
    from unittest.mock import Mock

    client = Mock()
    factory = Mock(return_value=client)
    monkeypatch.setattr("app.services.permanent_address_geocoder.boto3.client", factory)
    AmazonAddressGeocoder()._reverse_request((12.3, 77.6))
    client.reverse_geocode.assert_called_once_with(
        QueryPosition=[77.6, 12.3],
        QueryRadius=75,
        MaxResults=5,
        Filter={"IncludePlaceTypes": ["PointAddress", "InterpolatedAddress"]},
        IntendedUse="SingleUse",
        Language="en",
    )
    assert factory.call_args.kwargs["config"].retries["total_max_attempts"] == 1
    assert factory.call_args.kwargs["config"].connect_timeout == 3
    assert factory.call_args.kwargs["config"].read_timeout == 10
    client.geocode.assert_not_called()
