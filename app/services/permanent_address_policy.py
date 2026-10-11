"""Server-owned location, day-count and document conjunction policies."""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from app.schemas.permanent_address import LocationSample
from app.services.permanent_address_quality import (
    STREET_UNAVAILABLE_QUALITY,
    STREET_UNAVAILABLE_RADIUS_M,
    normalize,
    street_normalize,
)

ADDRESS_TIMEZONE = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class LocationPolicy:
    precise_radius_m: float = 100
    approximate_radius_m: float = 150
    street_unavailable_radius_m: float = STREET_UNAVAILABLE_RADIUS_M
    maximum_accuracy_m: float = 50
    maximum_dispersion_m: float = 50
    min_seconds: int = 30
    max_seconds: int = 60

    def __post_init__(self):
        if not (
            0 < self.precise_radius_m <= 100
            and 0 < self.approximate_radius_m <= 150
            and 0 < self.street_unavailable_radius_m <= STREET_UNAVAILABLE_RADIUS_M
            and 0 < self.maximum_accuracy_m <= 50
            and 0 < self.maximum_dispersion_m <= 50
            and 30 <= self.min_seconds <= self.max_seconds <= 60
        ):
            raise ValueError("Unsafe location policy")


@dataclass(frozen=True)
class LocationOutcome:
    result: str
    accuracy_m: float | None = None
    distance_m: float | None = None
    sample_count: int = 0
    mock_detected: bool = False


def metres(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    value = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 6371008.8 * 2 * math.asin(min(1, math.sqrt(max(0, value))))


def evaluate_location(
    samples: list[LocationSample],
    target: tuple[float, float],
    started_at: datetime,
    now: datetime,
    quality: str,
    policy: LocationPolicy | None = None,
) -> LocationOutcome:
    policy = policy or LocationPolicy()
    if quality not in {"precise_address", "approximate_address", STREET_UNAVAILABLE_QUALITY}:
        return LocationOutcome("NEEDS_REVIEW")
    if any(sample.mock_location for sample in samples):
        return LocationOutcome("NEEDS_REVIEW", sample_count=len(samples), mock_detected=True)
    elapsed = (now - started_at).total_seconds()
    if not (policy.min_seconds <= elapsed <= 120) or not 5 <= len(samples) <= 10:
        return LocationOutcome("RETRY_REQUIRED")
    ordered = sorted(samples, key=lambda s: s.timestamp)
    times = [sample.timestamp for sample in ordered]
    if len(set(times)) != len(times) or any(
        t < started_at - timedelta(seconds=2) or t > now + timedelta(seconds=2) for t in times
    ):
        return LocationOutcome("RETRY_REQUIRED")
    if not policy.min_seconds <= (times[-1] - times[0]).total_seconds() <= policy.max_seconds:
        return LocationOutcome("RETRY_REQUIRED")
    good = [sample for sample in ordered if sample.accuracy_m <= policy.maximum_accuracy_m]
    if (
        len(good) < 5
        or (good[-1].timestamp - good[0].timestamp).total_seconds() < policy.min_seconds
    ):
        return LocationOutcome("RETRY_REQUIRED", sample_count=len(good))
    representative = (median(s.latitude for s in good), median(s.longitude for s in good))
    spread = [metres(representative, (s.latitude, s.longitude)) for s in good]
    if max(spread) > policy.maximum_dispersion_m:
        return LocationOutcome("RETRY_REQUIRED", sample_count=len(good))
    accuracy = median(s.accuracy_m for s in good)
    radius = (
        policy.approximate_radius_m if quality == "approximate_address" else policy.precise_radius_m
    )
    if quality == STREET_UNAVAILABLE_QUALITY:
        radius = policy.street_unavailable_radius_m
    # Reported inaccuracy can never enlarge the configured base radius.
    effective_radius = max(radius, min(accuracy, policy.maximum_accuracy_m))
    distance = metres(representative, target)
    return LocationOutcome(
        "MATCHED" if distance <= effective_radius else "OUTSIDE_EXPECTED_AREA",
        round(accuracy, 1),
        round(distance, 1),
        len(good),
    )


def calendar_day(now: datetime):
    return now.astimezone(ADDRESS_TIMEZONE).date()


def count_days(days, window_start: datetime | None, now: datetime) -> int:
    if window_start is None or now >= window_start + timedelta(days=7):
        return 0
    first, last = calendar_day(window_start), calendar_day(now)
    return min(3, len({day for day in days if first <= day <= last}))


def document_match(claimed: dict, observed: dict) -> str:
    for key in ("country", "state", "city", "postal_code"):
        if not claimed.get(key) or not observed.get(key):
            return "NEEDS_REVIEW"
        if normalize(claimed[key]) != normalize(observed[key]):
            return "MISMATCH"
    # A unit or address-line conflict cannot be hidden by PIN/city agreement.
    for key in ("address_line_1", "address_line_2", "locality"):
        if street_normalize(claimed.get(key)) != street_normalize(observed.get(key)):
            return "NEEDS_REVIEW"
    return "MATCH"


def overall_status(
    document_status: str, checks: int, geocode_status: str, *, checking=False
) -> str:
    if document_status == "MATCH" and checks >= 3 and geocode_status == "READY":
        return "PERMANENT_ADDRESS_VERIFIED"
    if checks >= 3:
        return "LOCATION_CONFIRMED"
    if geocode_status in {"NEEDS_REVIEW", "FAILED"} or document_status in {
        "MISMATCH",
        "NEEDS_REVIEW",
    }:
        return "NEEDS_REVIEW"
    if checking:
        return "LOCATION_CHECK_IN_PROGRESS"
    if document_status == "REQUIRED":
        return "DOCUMENT_REQUIRED"
    if document_status == "PENDING":
        return "DOCUMENT_UNDER_REVIEW"
    return "LOCATION_CHECK_REQUIRED"
