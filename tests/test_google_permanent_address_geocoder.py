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


def with_component(result, component_type, long_name, short_name=None):
    without_component(result, component_type)
    result["address_components"].append(
        {
            "long_name": long_name,
            "short_name": short_name or long_name,
            "types": [component_type],
        }
    )
    return result


def partial_composite_result(*, location_type="RANGE_INTERPOLATED", result_types=None):
    result = google_result(
        partial=True,
        location_type=location_type,
        result_types=result_types or ["street_address"],
    )
    return with_component(result, "street_number", "8")


COMPOSITE_ADDRESS = {
    **ADDRESS,
    "address_line_1": "Flat 8, Synthetic Road, Example Enclave",
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


@pytest.mark.asyncio
async def test_google_complete_partial_composite_street_uses_interpolated_caution_path(
    diagnostic_stream,
):
    result = partial_composite_result()
    service, _ = geocoder(Response(payload={"status": "OK", "results": [result]}))
    metadata, target = await service.geocode(COMPOSITE_ADDRESS)
    assert target is not None
    assert metadata["quality"] == "approximate_address"
    assert metadata["classification"] == "GPS_TARGET_ELIGIBLE_WITH_CAUTION"
    assert metadata["street_status"] == "matched"
    assert "composite_street_reconciled" in metadata["warnings"]
    diagnostic = diagnostic_record(diagnostic_stream)
    assert diagnostic["partial_match"] is True
    assert diagnostic["provider_neutral_quality"] == "approximate_address"
    assert diagnostic["normalized_result_eligible"] is True


@pytest.mark.asyncio
async def test_google_partial_route_allows_only_missing_terminal_designator(
    diagnostic_stream,
):
    result = with_component(
        partial_composite_result(), "route", "Synthetic Central Road"
    )
    address = {
        **COMPOSITE_ADDRESS,
        "address_line_1": "Flat 8, Synthetic Central, Example Enclave",
    }
    service, _ = geocoder(Response(payload={"status": "OK", "results": [result]}))
    metadata, target = await service.geocode(address)
    assert target is not None
    assert metadata["classification"] == "GPS_TARGET_ELIGIBLE_WITH_CAUTION"
    assert metadata["quality"] == "approximate_address"
    assert metadata["radius_m"] == 150
    assert metadata["street_status"] == "matched"
    diagnostic = diagnostic_record(diagnostic_stream)
    assert diagnostic["partial_match"] is True
    assert diagnostic["normalized_result_eligible"] is True


@pytest.mark.parametrize(
    ("component_type", "long_name", "short_name", "reason"),
    [
        ("postal_code", "400001", "400001", "pin_mismatch_or_missing"),
        ("administrative_area_level_1", "Karnataka", "KA", "state_mismatch"),
        ("locality", "Mumbai", "Mumbai", "locality_mismatch"),
    ],
)
@pytest.mark.asyncio
async def test_google_partial_composite_street_never_overrides_component_conflicts(
    component_type, long_name, short_name, reason, diagnostic_stream
):
    result = with_component(
        partial_composite_result(), component_type, long_name, short_name
    )
    service, _ = geocoder(Response(payload={"status": "OK", "results": [result]}))
    metadata, target = await service.geocode(COMPOSITE_ADDRESS)
    assert target is None
    assert metadata["classification"] == "ADDRESS_NEEDS_REVIEW"
    assert reason in diagnostic_record(diagnostic_stream)["eligibility_reasons"]


@pytest.mark.parametrize(
    ("claimed_line", "provider_route"),
    [
        ("Flat 8, Different Road, Example Enclave", "Synthetic Road"),
        ("Flat 8, Rd, Example Enclave", "Rd"),
    ],
)
@pytest.mark.asyncio
async def test_google_partial_composite_street_rejects_unrelated_or_ambiguous_route(
    claimed_line, provider_route, diagnostic_stream
):
    result = with_component(partial_composite_result(), "route", provider_route)
    service, _ = geocoder(Response(payload={"status": "OK", "results": [result]}))
    metadata, target = await service.geocode(
        {**COMPOSITE_ADDRESS, "address_line_1": claimed_line}
    )
    assert target is None
    assert metadata["classification"] == "ADDRESS_NEEDS_REVIEW"
    assert "street_missing_or_mismatch" in diagnostic_record(diagnostic_stream)[
        "eligibility_reasons"
    ]


@pytest.mark.parametrize("location_type", ["GEOMETRIC_CENTER", "APPROXIMATE"])
@pytest.mark.asyncio
async def test_google_partial_composite_street_rejects_broad_location_types(
    location_type, diagnostic_stream
):
    result = partial_composite_result(location_type=location_type)
    service, _ = geocoder(Response(payload={"status": "OK", "results": [result]}))
    metadata, target = await service.geocode(COMPOSITE_ADDRESS)
    assert target is None
    assert metadata["classification"] == "ADDRESS_NEEDS_REVIEW"
    assert "broad_or_unsupported_place_type" in diagnostic_record(diagnostic_stream)[
        "eligibility_reasons"
    ]


@pytest.mark.asyncio
async def test_google_partial_route_only_result_remains_ineligible(diagnostic_stream):
    result = partial_composite_result(result_types=["route"])
    service, _ = geocoder(Response(payload={"status": "OK", "results": [result]}))
    metadata, target = await service.geocode(COMPOSITE_ADDRESS)
    assert target is None
    assert metadata["classification"] == "ADDRESS_NEEDS_REVIEW"
    assert "broad_or_unsupported_place_type" in diagnostic_record(diagnostic_stream)[
        "eligibility_reasons"
    ]


@pytest.mark.asyncio
async def test_google_competing_partial_composite_candidates_remain_ineligible(
    diagnostic_stream,
):
    service, _ = geocoder(
        Response(
            payload={
                "status": "OK",
                "results": [partial_composite_result(), partial_composite_result()],
            }
        )
    )
    metadata, target = await service.geocode(COMPOSITE_ADDRESS)
    assert target is None
    assert metadata["reasons"] == ("competing_candidates",)
    assert diagnostic_record(diagnostic_stream)["normalized_result_eligible"] is False


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


def test_google_partial_composite_matches_aws_interpolated_policy_semantics():
    google_item = module.normalize_google_result(partial_composite_result())
    aws_equivalent = {
        **google_item,
        "PlaceType": "InterpolatedAddress",
        "EstimatedPointAddress": False,
    }
    query = module.query_components(COMPOSITE_ADDRESS)
    google_decision = module.evaluate_targets([google_item], query)
    aws_decision = module.evaluate_targets([aws_equivalent], query)
    assert google_item["PlaceType"] == "InterpolatedAddress"
    assert google_item["EstimatedPointAddress"] is False
    assert google_decision == aws_decision
    assert google_decision.classification == "GPS_TARGET_ELIGIBLE_WITH_CAUTION"
    assert google_decision.quality == "approximate_address"
    assert google_decision.radius_m == 150


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
