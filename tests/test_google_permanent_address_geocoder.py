import io
import json
import logging
from unittest.mock import Mock

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.exceptions import ServiceUnavailableError
from app.logging.places import (
    GoogleDiagnosticFormatter,
    configure_places_logging,
    google_diagnostic_logger,
    logger,
)
from app.services import permanent_address_geocoder as module
from tests.test_permanent_address_geocoder import ADDRESS


def google_result(*, partial=False, location_type="ROOFTOP", result_types=None):
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
        "types": result_types or ["street_address"],
    }


def without_component(result, component_type):
    result["address_components"] = [
        component
        for component in result["address_components"]
        if component_type not in component["types"]
    ]
    return result


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


@pytest.fixture
def diagnostic_stream():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(GoogleDiagnosticFormatter("test"))
    old_handlers, old_level = google_diagnostic_logger.handlers[:], google_diagnostic_logger.level
    google_diagnostic_logger.handlers[:] = [handler]
    google_diagnostic_logger.setLevel(logging.INFO)
    try:
        yield stream
    finally:
        google_diagnostic_logger.handlers[:], google_diagnostic_logger.level = (
            old_handlers,
            old_level,
        )


def diagnostic_record(stream):
    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert len(records) == 1
    return records[0]


@pytest.mark.asyncio
async def test_google_forward_geocode_normalizes_without_raw_payload(diagnostic_stream):
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
    diagnostic = diagnostic_record(diagnostic_stream)
    assert diagnostic["reason"] == "GOOGLE_GEOCODE_SUCCESS"
    assert diagnostic["http_status"] == 200
    assert diagnostic["google_status"] == "OK"
    assert diagnostic["result_count"] == 1
    assert diagnostic["coordinates_present"] is True
    assert diagnostic["normalized_result_eligible"] is True


@pytest.mark.asyncio
async def test_google_place_id_geocode_uses_authoritative_selected_target(diagnostic_stream):
    service, observed = geocoder(
        Response(payload={"status": "OK", "results": [google_result()]})
    )
    metadata, target = await service.geocode_place_id(
        ADDRESS, "ChIJ-synthetic-place"
    )
    assert metadata["resolution_mode"] == "place_id"
    assert metadata["structured_parity"] is True
    assert target["position"] == [75.7628, 26.8505]
    params = observed["request_kwargs"]["params"]
    assert params["place_id"] == "ChIJ-synthetic-place"
    assert "address" not in params and "components" not in params
    diagnostic = diagnostic_record(diagnostic_stream)
    assert diagnostic["operation"] == "place_id_geocode"
    assert diagnostic["reason"] == "GOOGLE_GEOCODE_SUCCESS"


@pytest.mark.parametrize(
    ("component_type", "replacement", "reason"),
    [
        ("postal_code", "400001", "pin_mismatch_or_missing"),
        ("administrative_area_level_1", "Gujarat", "state_mismatch"),
        ("country", "US", "country_mismatch"),
    ],
)
@pytest.mark.asyncio
async def test_google_place_id_structural_mismatch_fails_closed(
    component_type, replacement, reason, diagnostic_stream
):
    result = google_result()
    component = next(
        value for value in result["address_components"] if component_type in value["types"]
    )
    component["long_name"] = replacement
    component["short_name"] = replacement
    service, _ = geocoder(Response(payload={"status": "OK", "results": [result]}))
    metadata, target = await service.geocode_place_id(
        ADDRESS, "ChIJ-synthetic-place"
    )
    assert target is None
    assert metadata["structured_parity"] is False
    assert reason in metadata["reasons"]
    diagnostic = diagnostic_record(diagnostic_stream)
    assert diagnostic["operation"] == "place_id_geocode"
    assert diagnostic["reason"] == "GOOGLE_GEOCODE_POLICY_INELIGIBLE"


@pytest.mark.asyncio
async def test_google_place_id_not_found_never_falls_back_to_text(diagnostic_stream):
    service, observed = geocoder(Response(payload={"status": "ZERO_RESULTS", "results": []}))
    metadata, target = await service.geocode_place_id(
        ADDRESS, "obsolete-place-id"
    )
    assert target is None
    assert metadata["resolution_mode"] == "place_id"
    params = observed["request_kwargs"]["params"]
    assert params["place_id"] == "obsolete-place-id"
    assert "address" not in params
    diagnostic = diagnostic_record(diagnostic_stream)
    assert diagnostic["reason"] == "GOOGLE_GEOCODE_ZERO_RESULTS"


@pytest.mark.asyncio
async def test_google_place_id_timeout_is_sanitized_without_text_retry():
    service, observed = geocoder(httpx.ReadTimeout("synthetic timeout"))
    with pytest.raises(ServiceUnavailableError):
        await service.geocode_place_id(ADDRESS, "ChIJ-synthetic-place")
    params = observed["request_kwargs"]["params"]
    assert params["place_id"] == "ChIJ-synthetic-place"
    assert "address" not in params


@pytest.mark.parametrize("result_type", ["premise", "subpremise"])
@pytest.mark.asyncio
async def test_google_rooftop_precise_result_types_are_eligible(
    result_type, diagnostic_stream
):
    service, _ = geocoder(
        Response(
            payload={
                "status": "OK",
                "results": [google_result(result_types=[result_type])],
            }
        )
    )
    metadata, target = await service.geocode(ADDRESS)
    assert target is not None
    assert metadata["quality"] == "precise_address"
    diagnostic = diagnostic_record(diagnostic_stream)
    assert diagnostic["selected_result_type_class"] == result_type
    assert diagnostic["provider_neutral_quality"] == "precise_address"


@pytest.mark.asyncio
async def test_google_range_interpolated_preserves_approximate_policy(diagnostic_stream):
    service, _ = geocoder(
        Response(
            payload={
                "status": "OK",
                "results": [google_result(location_type="RANGE_INTERPOLATED")],
            }
        )
    )
    metadata, target = await service.geocode(ADDRESS)
    assert target is not None
    assert metadata["quality"] == "approximate_address"
    assert metadata["classification"] == "GPS_TARGET_ELIGIBLE_WITH_CAUTION"
    diagnostic = diagnostic_record(diagnostic_stream)
    assert diagnostic["google_location_type"] == "RANGE_INTERPOLATED"
    assert diagnostic["provider_neutral_quality"] == "approximate_address"


@pytest.mark.parametrize("location_type", ["GEOMETRIC_CENTER", "APPROXIMATE"])
@pytest.mark.asyncio
async def test_google_broad_location_types_remain_ineligible(
    location_type, diagnostic_stream
):
    service, _ = geocoder(
        Response(
            payload={
                "status": "OK",
                "results": [google_result(location_type=location_type)],
            }
        )
    )
    metadata, target = await service.geocode(ADDRESS)
    assert target is None
    assert metadata["classification"] == "ADDRESS_NEEDS_REVIEW"
    diagnostic = diagnostic_record(diagnostic_stream)
    assert diagnostic["google_location_type"] == location_type
    assert "broad_or_unsupported_place_type" in diagnostic["eligibility_reasons"]


@pytest.mark.asyncio
async def test_google_partial_match_remains_ineligible(diagnostic_stream):
    service, _ = geocoder(
        Response(payload={"status": "OK", "results": [google_result(partial=True)]})
    )
    metadata, target = await service.geocode(ADDRESS)
    assert target is None
    assert metadata["classification"] == "ADDRESS_NEEDS_REVIEW"
    diagnostic = diagnostic_record(diagnostic_stream)
    assert diagnostic["partial_match"] is True
    assert "broad_or_unsupported_place_type" in diagnostic["eligibility_reasons"]


@pytest.mark.parametrize(
    ("component_type", "presence_key", "reason"),
    [
        ("postal_code", "postal_code", "pin_mismatch_or_missing"),
        ("locality", "locality", "locality_mismatch"),
    ],
)
@pytest.mark.asyncio
async def test_google_missing_required_components_remain_ineligible(
    component_type, presence_key, reason, diagnostic_stream
):
    result = without_component(google_result(), component_type)
    service, _ = geocoder(Response(payload={"status": "OK", "results": [result]}))
    metadata, target = await service.geocode(ADDRESS)
    assert target is None
    assert metadata["classification"] == "ADDRESS_NEEDS_REVIEW"
    diagnostic = diagnostic_record(diagnostic_stream)
    assert diagnostic["required_component_presence"][presence_key] is False
    assert reason in diagnostic["eligibility_reasons"]


@pytest.mark.parametrize("result_type", ["locality", "postal_code"])
@pytest.mark.asyncio
async def test_google_non_address_result_types_remain_ineligible(
    result_type, diagnostic_stream
):
    service, _ = geocoder(
        Response(
            payload={
                "status": "OK",
                "results": [
                    google_result(
                        location_type="ROOFTOP",
                        result_types=[result_type],
                    )
                ],
            }
        )
    )
    metadata, target = await service.geocode(ADDRESS)
    assert target is None
    assert metadata["classification"] == "ADDRESS_NEEDS_REVIEW"
    diagnostic = diagnostic_record(diagnostic_stream)
    assert diagnostic["selected_result_type_class"] == result_type
    assert "broad_or_unsupported_place_type" in diagnostic["eligibility_reasons"]


@pytest.mark.asyncio
async def test_google_multiple_results_selects_only_precise_candidate(diagnostic_stream):
    broad = google_result(location_type="APPROXIMATE", result_types=["locality"])
    precise = google_result()
    service, _ = geocoder(
        Response(payload={"status": "OK", "results": [broad, precise]})
    )
    metadata, target = await service.geocode(ADDRESS)
    assert target is not None
    assert metadata["selected_index"] == 0
    assert metadata["quality"] == "precise_address"
    diagnostic = diagnostic_record(diagnostic_stream)
    assert diagnostic["selected_result_type_class"] == "street_address"
    assert diagnostic["result_count"] == 2


@pytest.mark.asyncio
async def test_google_route_geometric_center_without_postal_code_is_ineligible(
    diagnostic_stream,
):
    result = without_component(
        google_result(
            location_type="GEOMETRIC_CENTER",
            result_types=["route"],
        ),
        "postal_code",
    )
    service, _ = geocoder(Response(payload={"status": "OK", "results": [result]}))
    metadata, target = await service.geocode(ADDRESS)
    assert target is None
    assert metadata["reasons"] == ("no_eligible_target",)
    diagnostic = diagnostic_record(diagnostic_stream)
    assert diagnostic["coordinates_present"] is True
    assert diagnostic["required_component_presence"]["postal_code"] is False
    assert set(diagnostic["eligibility_reasons"]) == {
        "no_eligible_target",
        "pin_mismatch_or_missing",
        "broad_or_unsupported_place_type",
    }


def test_google_quality_mapping_matches_aws_provider_neutral_semantics():
    google_item = module.normalize_google_result(google_result())
    aws_equivalent = {
        **google_item,
        "PlaceType": "PointAddress",
        "EstimatedPointAddress": False,
    }
    query = module.query_components(ADDRESS)
    google_decision = module.evaluate_targets([google_item], query)
    aws_decision = module.evaluate_targets([aws_equivalent], query)
    assert google_item["PlaceType"] == "PointAddress"
    assert google_decision.classification == aws_decision.classification
    assert google_decision.quality == aws_decision.quality == "precise_address"
    assert google_decision.eligible is aws_decision.eligible is True


@pytest.mark.asyncio
async def test_google_reverse_geocode_uses_existing_area_policy():
    service, observed = geocoder(Response(payload={"status": "OK", "results": [google_result()]}))
    decision = await service.confirm_area(ADDRESS, (26.8505, 75.7628))
    assert decision["accepted"] is True
    params = observed["request_kwargs"]["params"]
    assert params["latlng"] == "26.8505,75.7628"
    assert params["result_type"] == "street_address"


@pytest.mark.asyncio
async def test_zero_results_fail_closed_without_target(diagnostic_stream):
    service, _ = geocoder(Response(payload={"status": "ZERO_RESULTS", "results": []}))
    metadata, target = await service.geocode(ADDRESS)
    assert target is None
    assert metadata["provider"] == "google"
    assert metadata["reasons"] == ("no_eligible_target",)
    diagnostic = diagnostic_record(diagnostic_stream)
    assert diagnostic["reason"] == "GOOGLE_GEOCODE_ZERO_RESULTS"
    assert diagnostic["result_count"] == 0
    assert diagnostic["coordinates_present"] is False


@pytest.mark.parametrize(
    ("status_code", "reason"),
    [
        (400, "GOOGLE_GEOCODE_PROVIDER_4XX"),
        (401, "GOOGLE_GEOCODE_AUTH_FAILURE"),
        (403, "GOOGLE_GEOCODE_AUTH_FAILURE"),
        (429, "GOOGLE_GEOCODE_QUOTA_OR_RATE_LIMIT"),
        (500, "GOOGLE_GEOCODE_PROVIDER_5XX"),
        (503, "GOOGLE_GEOCODE_PROVIDER_5XX"),
    ],
)
@pytest.mark.asyncio
async def test_google_http_failures_are_sanitized(status_code, reason, diagnostic_stream):
    service, _ = geocoder(Response(status_code=status_code, payload={"private": "value"}))
    with pytest.raises(ServiceUnavailableError) as error:
        await service.geocode(ADDRESS)
    assert str(error.value) == "Address lookup is temporarily unavailable"
    diagnostic = diagnostic_record(diagnostic_stream)
    assert diagnostic["reason"] == reason
    assert diagnostic["http_status"] == status_code


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


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (httpx.ReadTimeout("synthetic timeout"), "GOOGLE_GEOCODE_TIMEOUT"),
        (httpx.ConnectError("synthetic network error"), "GOOGLE_GEOCODE_NETWORK_FAILURE"),
        (
            Response(payload=ValueError("synthetic malformed json")),
            "GOOGLE_GEOCODE_MALFORMED_RESPONSE",
        ),
        (Response(payload=[]), "GOOGLE_GEOCODE_MALFORMED_RESPONSE"),
        (
            Response(payload={"status": "OK", "results": {}}),
            "GOOGLE_GEOCODE_MALFORMED_RESPONSE",
        ),
    ],
)
@pytest.mark.asyncio
async def test_google_transport_and_payload_diagnostic_mapping(
    response, reason, diagnostic_stream
):
    service, _ = geocoder(response)
    with pytest.raises(ServiceUnavailableError):
        await service.geocode(ADDRESS)
    assert diagnostic_record(diagnostic_stream)["reason"] == reason


@pytest.mark.asyncio
async def test_google_missing_coordinates_are_classified(diagnostic_stream):
    result = google_result()
    result["geometry"]["location"] = {}
    service, _ = geocoder(Response(payload={"status": "OK", "results": [result]}))
    with pytest.raises(ServiceUnavailableError):
        await service.geocode(ADDRESS)
    diagnostic = diagnostic_record(diagnostic_stream)
    assert diagnostic["reason"] == "GOOGLE_GEOCODE_MISSING_COORDINATES"
    assert diagnostic["coordinates_present"] is False


@pytest.mark.asyncio
async def test_google_normalization_failure_is_classified(monkeypatch, diagnostic_stream):
    service, _ = geocoder(Response(payload={"status": "OK", "results": [google_result()]}))
    monkeypatch.setattr(
        module,
        "normalize_google_result",
        Mock(side_effect=ValueError("synthetic normalization failure")),
    )
    with pytest.raises(ServiceUnavailableError):
        await service.geocode(ADDRESS)
    diagnostic = diagnostic_record(diagnostic_stream)
    assert diagnostic["reason"] == "GOOGLE_GEOCODE_NORMALIZATION_FAILURE"
    assert diagnostic["coordinates_present"] is True


@pytest.mark.asyncio
async def test_google_policy_ineligible_result_is_classified(diagnostic_stream):
    service, _ = geocoder(
        Response(payload={"status": "OK", "results": [google_result(partial=True)]})
    )
    metadata, target = await service.geocode(ADDRESS)
    assert target is None
    assert metadata["classification"] == "ADDRESS_NEEDS_REVIEW"
    diagnostic = diagnostic_record(diagnostic_stream)
    assert diagnostic["reason"] == "GOOGLE_GEOCODE_POLICY_INELIGIBLE"
    assert diagnostic["coordinates_present"] is True
    assert diagnostic["normalized_result_eligible"] is False


@pytest.mark.asyncio
async def test_google_secret_address_and_coordinates_are_not_logged():
    service, _ = geocoder(Response(status_code=403, payload={"status": "REQUEST_DENIED"}))
    stream = io.StringIO()
    old_handlers, old_level = logger.handlers[:], logger.level
    old_diagnostic_handlers = google_diagnostic_logger.handlers[:]
    old_diagnostic_level = google_diagnostic_logger.level
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("app.logging.places.sys.stdout", stream)
    configure_places_logging("production")
    try:
        with pytest.raises(ServiceUnavailableError):
            await service.geocode(ADDRESS)
    finally:
        logger.handlers[:], logger.level = old_handlers, old_level
        google_diagnostic_logger.handlers[:], google_diagnostic_logger.level = (
            old_diagnostic_handlers,
            old_diagnostic_level,
        )
        monkeypatch.undo()
    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    places_records = [row for row in records if row["event"] == "permanent_address.places_call"]
    assert [row["outcome"] for row in places_records] == ["started", "failed"]
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
