import io
import json
from unittest.mock import Mock

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.exceptions import ServiceUnavailableError
from app.logging.places import configure_places_logging, logger
from app.services import permanent_address_geocoder as module
from tests.test_permanent_address_geocoder import ADDRESS


def google_result(*, partial=False, location_type="ROOFTOP"):
    return {
        "formatted_address": "Synthetic Road, Jaipur, Rajasthan 302020, India",
        "partial_match": partial,
        "address_components": [
            {"long_name": "Synthetic Road", "short_name": "Synthetic Rd", "types": ["route"]},
            {"long_name": "Jaipur", "short_name": "Jaipur", "types": ["locality"]},
            {
                "long_name": "Rajasthan",
                "short_name": "RJ",
                "types": ["administrative_area_level_1"],
            },
            {"long_name": "302020", "short_name": "302020", "types": ["postal_code"]},
            {"long_name": "India", "short_name": "IN", "types": ["country"]},
        ],
        "geometry": {
            "location": {"lat": 26.8505, "lng": 75.7628},
            "location_type": location_type,
        },
        "types": ["street_address"],
    }


class Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.request = httpx.Request("GET", module.GOOGLE_GEOCODING_URL)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "provider request failed",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class Client:
    def __init__(self, response, observed, **kwargs):
        self.response = response
        self.observed = observed
        observed["client_kwargs"] = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, **kwargs):
        self.observed["url"] = url
        self.observed["request_kwargs"] = kwargs
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def geocoder(response):
    observed = {}

    def factory(**kwargs):
        return Client(response, observed, **kwargs)

    return module.GoogleAddressGeocoder(
        api_key=SecretStr("synthetic-private-google-key"),
        client_factory=factory,
    ), observed


@pytest.mark.asyncio
async def test_google_forward_geocode_normalizes_without_raw_payload():
    service, observed = geocoder(Response(payload={"status": "OK", "results": [google_result()]}))
    metadata, target = await service.geocode(ADDRESS)
    assert metadata["provider"] == "google"
    assert metadata["quality"] == "precise_address"
    assert metadata["classification"] == "GPS_TARGET_ELIGIBLE"
    assert target["position"] == [75.7628, 26.8505]
    assert target["normalized_address"]["PostalCode"] == "302020"
    assert "formatted_address" not in repr(metadata)
    assert observed["url"] == module.GOOGLE_GEOCODING_URL
    params = observed["request_kwargs"]["params"]
    assert params["address"].startswith("Synthetic Road")
    assert params["components"] == "country:IN"
    assert params["key"] == "synthetic-private-google-key"
    assert observed["client_kwargs"]["follow_redirects"] is False


@pytest.mark.asyncio
async def test_google_reverse_geocode_uses_existing_area_policy():
    service, observed = geocoder(Response(payload={"status": "OK", "results": [google_result()]}))
    decision = await service.confirm_area(ADDRESS, (26.8505, 75.7628))
    assert decision["accepted"] is True
    params = observed["request_kwargs"]["params"]
    assert params["latlng"] == "26.8505,75.7628"
    assert params["result_type"] == "street_address"


@pytest.mark.asyncio
async def test_zero_results_fail_closed_without_target():
    service, _ = geocoder(Response(payload={"status": "ZERO_RESULTS", "results": []}))
    metadata, target = await service.geocode(ADDRESS)
    assert target is None
    assert metadata["provider"] == "google"
    assert metadata["reasons"] == ("no_eligible_target",)


@pytest.mark.parametrize("status_code", [400, 401, 403, 429, 500, 503])
@pytest.mark.asyncio
async def test_google_http_failures_are_sanitized(status_code):
    service, _ = geocoder(Response(status_code=status_code, payload={"private": "value"}))
    with pytest.raises(ServiceUnavailableError) as error:
        await service.geocode(ADDRESS)
    assert str(error.value) == "Address lookup is temporarily unavailable"


@pytest.mark.parametrize(
    "response",
    [
        httpx.ReadTimeout("synthetic timeout"),
        httpx.ConnectError("synthetic network error"),
        Response(payload=ValueError("synthetic malformed json")),
        Response(payload=[]),
        Response(payload={"status": "OK", "results": {}}),
        Response(payload={"status": "REQUEST_DENIED", "error_message": "private"}),
        Response(payload={"status": "OVER_QUERY_LIMIT", "results": []}),
        Response(payload={"status": "UNKNOWN_ERROR", "results": []}),
    ],
)
@pytest.mark.asyncio
async def test_google_transport_and_payload_failures_are_sanitized(response):
    service, _ = geocoder(response)
    with pytest.raises(ServiceUnavailableError) as error:
        await service.geocode(ADDRESS)
    assert str(error.value) == "Address lookup is temporarily unavailable"


@pytest.mark.asyncio
async def test_google_secret_address_and_coordinates_are_not_logged():
    service, _ = geocoder(Response(status_code=403, payload={"status": "REQUEST_DENIED"}))
    stream = io.StringIO()
    old_handlers, old_level = logger.handlers[:], logger.level
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("app.logging.places.sys.stdout", stream)
    configure_places_logging("production")
    try:
        with pytest.raises(ServiceUnavailableError):
            await service.geocode(ADDRESS)
    finally:
        logger.handlers[:], logger.level = old_handlers, old_level
        monkeypatch.undo()
    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [row["outcome"] for row in records] == ["started", "failed"]
    assert all(row["provider"] == "google" for row in records)
    output = stream.getvalue()
    assert "synthetic-private-google-key" not in output
    assert "Synthetic Road" not in output
    assert "26.8505" not in output and "75.7628" not in output


def test_provider_selection_fails_closed_and_never_falls_back(monkeypatch):
    monkeypatch.setattr(module.boto3, "client", Mock(side_effect=AssertionError("AWS fallback")))
    with pytest.raises(ValidationError):
        Settings(PERMANENT_ADDRESS_GEOCODER_PROVIDER="unknown")
    with pytest.raises(ServiceUnavailableError):
        module.build_address_geocoder(
            type("UnsafeSettings", (), {"permanent_address_geocoder_provider": "unknown"})()
        )
