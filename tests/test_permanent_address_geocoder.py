import copy
import logging
from unittest.mock import Mock

import pytest

from app.exceptions import ServiceUnavailableError
from app.schemas.permanent_address import PermanentAddressInput
from app.services import permanent_address_geocoder as module

ADDRESS = {
    "address_line_1": "Synthetic Road",
    "address_line_2": "Synthetic Building Unit A",
    "locality": "Synthetic District",
    "city": "Jaipur",
    "state": "Rajasthan",
    "postal_code": "302020",
    "country": "IN",
}


@pytest.fixture
def provider(monkeypatch):
    client = Mock()
    client.geocode.return_value = {"ResultItems": []}
    factory = Mock(return_value=client)
    monkeypatch.setattr(module.boto3, "client", factory)
    return client, factory


@pytest.mark.parametrize("line2", [None, "", "   ", "Synthetic Building Unit A"])
@pytest.mark.parametrize("locality", [None, "Synthetic District"])
async def test_complete_context_and_unchanged_components(provider, line2, locality):
    client, factory = provider
    address = {**ADDRESS, "address_line_2": line2, "locality": locality}
    before = copy.deepcopy(address)
    metadata, target = await module.AmazonAddressGeocoder().geocode(address)
    client.geocode.assert_called_once()
    request = client.geocode.call_args.kwargs
    expected = [address["address_line_1"]]
    if line2 and line2.strip():
        expected.append(line2)
    if locality:
        expected.append(locality)
    expected.extend(["Jaipur", "Rajasthan", "302020", "IN"])
    assert request["QueryText"] == ", ".join(expected)
    components = {
        "Country": "IND", "Region": "Rajasthan", "Locality": "Jaipur",
        "PostalCode": "302020", "Street": "Synthetic Road",
    }
    if locality:
        components["District"] = locality
    assert request["QueryComponents"] == components
    assert request["Filter"] == {"IncludeCountries": ["IND"]}
    assert request["IntendedUse"] == "Storage"
    assert request["MaxResults"] == 10
    assert request["Language"] == "en"
    assert factory.call_args.kwargs["region_name"] == "us-east-1"
    assert factory.call_args.kwargs["config"].retries["total_max_attempts"] == 1
    assert address == before
    assert target is None
    assert metadata["reasons"] == ("no_eligible_target",)


@pytest.mark.parametrize("line", ["123 Synthetic Road", "Block 12 Unit 34", "12/A Sample"])
def test_no_number_inference_without_explicit_schema_field(line):
    assert "address_number" not in PermanentAddressInput.model_fields
    query = module.query_components({**ADDRESS, "address_line_1": line})
    assert "AddressNumber" not in query
    assert query["Street"] == line


@pytest.mark.parametrize("country", [None, "", "GB", "US", "IND"])
async def test_no_country_fallback_or_provider_call(provider, country):
    client, factory = provider
    with pytest.raises(ServiceUnavailableError):
        await module.AmazonAddressGeocoder().geocode({**ADDRESS, "country": country})
    factory.assert_not_called()
    client.geocode.assert_not_called()


async def test_overlong_query_is_not_truncated_or_sent(provider):
    client, factory = provider
    address = {**ADDRESS, "address_line_2": "X" * 160}
    with pytest.raises(ServiceUnavailableError):
        await module.AmazonAddressGeocoder().geocode(address)
    factory.assert_not_called()
    client.geocode.assert_not_called()


@pytest.mark.parametrize("fails", [False, True])
async def test_no_address_in_logs_metadata_or_public_error(provider, caplog, fails):
    client, _ = provider
    private = module.query_text(ADDRESS)
    if fails:
        client.geocode.side_effect = RuntimeError(private)
    with caplog.at_level(logging.INFO, logger=module.__name__):
        if fails:
            with pytest.raises(ServiceUnavailableError) as error:
                await module.AmazonAddressGeocoder().geocode(ADDRESS)
            output = str(error.value)
        else:
            output = repr(await module.AmazonAddressGeocoder().geocode(ADDRESS))
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.getMessage() == "permanent_address.geocode_request"
    assert record.request_count == 1
    assert not record.exc_info
    for key, value in ADDRESS.items():
        if key == "country":
            continue
        assert value not in output + repr(record.__dict__)
    client.geocode.assert_called_once()


async def test_fallback_returns_private_target_and_safe_metadata(provider):
    from copy import deepcopy

    from tests.test_permanent_address_quality import missing_street

    client, _ = provider
    item = missing_street()
    item["MatchScores"]["Overall"] = 0.41
    original = deepcopy(ADDRESS)
    client.geocode.return_value = {"ResultItems": [item]}
    metadata, target = await module.AmazonAddressGeocoder(
        street_unavailable_radius_m=60,
    ).geocode(ADDRESS)
    assert metadata["quality"] == "precise_address_street_unavailable"
    assert metadata["street_status"] == "provider_unavailable"
    assert metadata["radius_m"] == 60
    assert metadata["candidates"][0]["component_matches"]["street"] is False
    assert target["position"] == [0.0, 0.0]
    assert ADDRESS == original
    for key in ("address_line_1", "address_line_2", "postal_code"):
        assert ADDRESS[key] not in repr(metadata)
