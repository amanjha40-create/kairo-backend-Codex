"""Synthetic-only target and distance audit; never use live coordinates."""

import math
from datetime import timedelta
from itertools import combinations
from statistics import median
from uuid import uuid4

import pytest

from app.exceptions import NotFoundError, ServiceUnavailableError
from app.models.permanent_address import PermanentAddressSession, PermanentAddressVersion
from app.schemas.permanent_address import LocationCompleteInput, LocationSample
from app.services import permanent_address_policy as policy
from app.services import permanent_address_service as service
from app.services.permanent_address_geocoder import TargetCipher
from tests.test_permanent_address_verification import (
    ADDRESS,
    NOW,
    case,  # noqa: F401 - shared local transaction fixture
    settings,
)


def reference_metres(a, b):
    # Independent unit-vector central angle, not the production haversine formula.
    def vector(point):
        latitude, longitude = map(math.radians, point)
        return (
            math.cos(latitude) * math.cos(longitude),
            math.cos(latitude) * math.sin(longitude),
            math.sin(latitude),
        )

    u, v = vector(a), vector(b)
    cross = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    angle = math.atan2(
        math.sqrt(sum(x * x for x in cross)), sum(x * y for x, y in zip(u, v, strict=True))
    )
    return 6371008.8 * angle


@pytest.mark.parametrize("point", [(0, 0), (13, 77), (-13, -77), (89.9, 179.9)])
def test_same_point_is_zero(point):
    assert policy.metres(point, point) == pytest.approx(0, abs=1e-9)


@pytest.mark.parametrize("distance", [50, 500])
@pytest.mark.parametrize("origin", [(0, 0), (13, 77), (-13, -77)])
def test_known_meridian_distance_and_independent_reference(origin, distance):
    target = (origin[0] + math.degrees(distance / 6371008.8), origin[1])
    assert policy.metres(origin, target) == pytest.approx(distance, abs=1e-6)
    assert policy.metres(origin, target) == pytest.approx(
        reference_metres(origin, target), abs=1e-6
    )
    assert policy.metres(target, origin) == pytest.approx(distance, abs=1e-6)


@pytest.mark.parametrize(
    "a,b",
    [
        ((13, 77), (13.001, 77.004)),
        ((0, 179.999), (0, -179.999)),
        ((-33.1, -70.2), (-33.101, -70.202)),
        ((89.99, 45), (89.99, -45)),
        ((0, 0), (0, 180)),
    ],
)
def test_independent_vector_reference(a, b):
    assert policy.metres(a, b) == pytest.approx(reference_metres(a, b), abs=1e-5)


@pytest.mark.parametrize(
    "position",
    [
        [77.1234567890123, 13.9876543210987],
        [-77.1234567890123, -13.9876543210987],
        [77.1234567890123, -13.9876543210987],
        [-77.1234567890123, 13.9876543210987],
    ],
)
def test_cipher_preserves_order_sign_precision_and_randomizes_nonce(position):
    cipher = TargetCipher(settings())
    owner, version = uuid4(), uuid4()
    target = {"position": position, "normalized_address": {}}
    first, second = (cipher.encrypt(target, owner, version) for _ in range(2))
    assert first != second
    for encrypted in (first, second):
        restored = cipher.decrypt(encrypted, cipher.active, owner, version)
        assert restored == target
        assert [v.hex() for v in restored["position"]] == [v.hex() for v in position]
    for wrong_owner, wrong_version in ((uuid4(), version), (owner, uuid4())):
        with pytest.raises(ServiceUnavailableError):
            cipher.decrypt(first, cipher.active, wrong_owner, wrong_version)
    tampered = first[:-1] + bytes([first[-1] ^ 1])
    with pytest.raises(ServiceUnavailableError):
        cipher.decrypt(tampered, cipher.active, owner, version)


def synthetic_samples():
    return [
        LocationSample(
            latitude=13 + x * 0.00001,
            longitude=77 + y * 0.00001,
            accuracy_m=15,
            timestamp=NOW + timedelta(seconds=i * 8),
        )
        for i, (x, y) in enumerate([(-2, 2), (-1, 1), (0, 0), (1, -1), (2, -2)])
    ]


def test_representative_uses_separate_medians_not_crossed_arrays(monkeypatch):
    values = synthetic_samples()
    representative = (median(s.latitude for s in values), median(s.longitude for s in values))
    calls = []
    original = policy.metres

    def capture(a, b):
        calls.append((a, b))
        return original(a, b)

    monkeypatch.setattr(policy, "metres", capture)
    result = policy.evaluate_location(
        list(reversed(values)),
        representative,
        NOW,
        NOW + timedelta(seconds=40),
        "precise_address_street_unavailable",
    )
    assert result.result == "MATCHED" and result.sample_count == 5
    assert result.distance_m == 0
    assert all(a == representative for a, _ in calls)
    assert [b for _, b in calls[:-1]] == [(s.latitude, s.longitude) for s in values]
    assert (
        max(
            reference_metres((a.latitude, a.longitude), (b.latitude, b.longitude))
            for a, b in combinations(values, 2)
        )
        < 10
    )
    assert any((s.latitude, s.longitude) == representative for s in values)


def test_inaccurate_outlier_is_excluded_from_representative():
    values = synthetic_samples()
    values.append(
        LocationSample(
            latitude=-13, longitude=-77, accuracy_m=51, timestamp=NOW + timedelta(seconds=40)
        )
    )
    result = policy.evaluate_location(
        values, (13, 77), NOW, NOW + timedelta(seconds=49), "precise_address_street_unavailable"
    )
    assert result.result == "MATCHED" and result.sample_count == 5 and result.distance_m == 0


def test_stale_sample_rejects_batch_before_distance(monkeypatch):
    values = synthetic_samples()
    values[0] = values[0].model_copy(update={"timestamp": NOW - timedelta(seconds=3)})

    def no_distance(*args):
        pytest.fail("Rejected batch must not reach distance evaluation")

    monkeypatch.setattr(policy, "metres", no_distance)
    assert (
        policy.evaluate_location(
            values, (13, 77), NOW, NOW + timedelta(seconds=40), "precise_address_street_unavailable"
        ).result
        == "RETRY_REQUIRED"
    )


async def test_service_target_order_linkage_and_derived_only_retention(case, monkeypatch):  # noqa: F811
    db, users, svc, clock, _ = case

    async def synthetic_geocode(address):
        return {"quality": "precise_address_street_unavailable", "provider": "synthetic"}, {
            "position": [77.0, 13.0],
            "normalized_address": {},
        }

    monkeypatch.setattr(svc.geocoder, "geocode", synthetic_geocode)
    state = await svc.save_address(users[0].id, ADDRESS)
    version = state.address_version_id
    challenge = await svc.start(users[0].id, version)
    captured = []
    original = service.evaluate_location

    def capture(samples, target, *args):
        captured.append(target)
        return original(samples, target, *args)

    monkeypatch.setattr(service, "evaluate_location", capture)
    clock[0] += timedelta(seconds=40)
    result = await svc.finish(
        users[0].id,
        challenge.session_id,
        LocationCompleteInput(challenge=challenge.challenge, samples=synthetic_samples()),
    )
    assert captured == [(13.0, 77.0)]
    assert result.last_location_result == "MATCHED"
    record = await db.get(PermanentAddressSession, challenge.session_id)
    assert record.address_version_id == version
    assert set(record.derived_evidence) == {
        "result",
        "accuracy_m",
        "distance_m",
        "sample_count",
        "mock_detected",
    }
    assert record.derived_evidence["distance_m"] == 0
    old = await db.get(PermanentAddressVersion, version)
    for owner, target_version in ((users[1].id, version), (users[0].id, uuid4())):
        with pytest.raises(NotFoundError):
            await svc.start(owner, target_version)
    newer = await svc.save_address(
        users[0].id, ADDRESS.model_copy(update={"address_line_2": "Synthetic second unit"})
    )
    assert newer.address_version_id != version and old.invalidated_at is not None
    with pytest.raises(NotFoundError):
        await svc.start(users[0].id, version)
