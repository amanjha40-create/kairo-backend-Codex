"""Backend-only geocoding and context-bound target encryption."""

import asyncio
import json
import math
import os
from dataclasses import asdict, dataclass
from uuid import uuid4

import boto3
import httpx
from botocore.config import Config
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.exceptions import ServiceUnavailableError
from app.integrations.digilocker.crypto import parse_keyring
from app.logging.places import log_google_geocode_diagnostic, places_call
from app.services.permanent_address_onsite import (
    MAX_PRECISE_RESULTS,
    PRECISE_PLACE_TYPES,
    precise_area_decision,
)
from app.services.permanent_address_quality import (
    POLICY_VERSION,
    STREET_UNAVAILABLE_RADIUS_M,
    evaluate_targets,
)

AMAZON_PROVIDER = "amazon_location"
GOOGLE_PROVIDER = "google"
GOOGLE_GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"


@dataclass(frozen=True)
class GoogleProviderResult:
    items: list[dict]
    correlation_id: str
    http_status: int
    google_status: str
    result_count: int
    coordinates_present: bool


class GoogleDiagnosticFailure(Exception):
    def __init__(
        self,
        reason,
        *,
        http_status=None,
        google_status=None,
        result_count=None,
        coordinates_present=False,
    ):
        super().__init__(reason)
        self.reason = reason
        self.http_status = http_status
        self.google_status = google_status
        self.result_count = result_count
        self.coordinates_present = coordinates_present


class TargetCipher:
    def __init__(self, settings):
        self.environment = str(settings.app_env)
        self.active = settings.permanent_address_key_id
        try:
            self.keys = parse_keyring(
                settings.permanent_address_keys, self.active, self.environment
            )
        except Exception:
            raise ServiceUnavailableError(
                "Address verification is temporarily unavailable"
            ) from None

    def aad(self, owner, version, key_id):
        return (
            f"kairoid:permanent-address:v1:{self.environment}:{owner}:{version}:{key_id}".encode()
        )

    def encrypt(self, value, owner, version):
        nonce = os.urandom(12)
        return nonce + AESGCM(self.keys[self.active]).encrypt(
            nonce,
            json.dumps(value, allow_nan=False).encode(),
            self.aad(owner, version, self.active),
        )

    def decrypt(self, value, key_id, owner, version):
        try:
            result = json.loads(
                AESGCM(self.keys[key_id]).decrypt(
                    value[:12], value[12:], self.aad(owner, version, key_id)
                )
            )
            point = result["position"]
            if (
                len(point) != 2
                or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in point)
                or not -180 <= point[0] <= 180
                or not -90 <= point[1] <= 90
            ):
                raise ValueError()
            return result
        except Exception:
            raise ServiceUnavailableError(
                "Address verification is temporarily unavailable"
            ) from None


def query_components(address):
    if address.get("country") != "IN":
        raise ServiceUnavailableError("Address lookup is temporarily unavailable")
    query = {
        "Country": "IND",
        "Region": address["state"],
        "Locality": address["city"],
        "PostalCode": address["postal_code"],
        "Street": address["address_line_1"],
    }
    # V1 has no explicit address-number field; do not infer one from free text.
    if address.get("locality"):
        query["District"] = address["locality"]
    return query


def query_text(address):
    value = ", ".join(
        part.strip()
        for field in (
            "address_line_1",
            "address_line_2",
            "locality",
            "city",
            "state",
            "postal_code",
            "country",
        )
        if (part := address.get(field)) and part.strip()
    )
    # Preserve complete context or fail closed; never silently truncate an address.
    if not 1 <= len(value) <= 200:
        raise ServiceUnavailableError("Address lookup is temporarily unavailable")
    return value


class AmazonAddressGeocoder:
    provider_name = AMAZON_PROVIDER

    def __init__(
        self,
        *,
        region="us-east-1",
        street_unavailable_radius_m=STREET_UNAVAILABLE_RADIUS_M,
    ):
        self.region = region
        self.street_unavailable_radius_m = street_unavailable_radius_m

    async def confirm_area(self, address, representative):
        try:
            response = await asyncio.to_thread(self._reverse_request, representative)
            return precise_area_decision(address, response.get("ResultItems", []))
        except Exception:
            raise ServiceUnavailableError("Address area confirmation is unavailable") from None

    def _reverse_request(self, representative):
        client = boto3.client(
            "geo-places",
            region_name=self.region,
            config=Config(connect_timeout=3, read_timeout=10, retries={"total_max_attempts": 1}),
        )
        with places_call("reverse_geocode"):
            return client.reverse_geocode(
                QueryPosition=[representative[1], representative[0]],
                QueryRadius=75,
                MaxResults=MAX_PRECISE_RESULTS,
                Filter={"IncludePlaceTypes": list(PRECISE_PLACE_TYPES)},
                IntendedUse="SingleUse",
                Language="en",
            )

    async def geocode(self, address):
        query = query_components(address)
        try:
            response = await asyncio.to_thread(self._request, query, query_text(address))
            items = response.get("ResultItems", [])
            decision = evaluate_targets(
                items, query, street_unavailable_radius_m=self.street_unavailable_radius_m
            )
            metadata = asdict(decision)
            metadata.update(provider=self.provider_name, policy_version=POLICY_VERSION)
            if not decision.eligible:
                return metadata, None
            chosen = items[decision.selected_index]
            private = {
                "position": chosen["Position"],
                "normalized_address": {
                    k: chosen.get("Address", {}).get(k)
                    for k in (
                        "Country",
                        "Region",
                        "Locality",
                        "PostalCode",
                        "Street",
                        "AddressNumber",
                    )
                },
            }
            return metadata, private
        except Exception:
            raise ServiceUnavailableError("Address lookup is temporarily unavailable") from None

    def _request(self, query, text):
        client = boto3.client(
            "geo-places",
            region_name=self.region,
            config=Config(connect_timeout=5, read_timeout=15, retries={"total_max_attempts": 1}),
        )
        with places_call("geocode"):
            return client.geocode(
                QueryComponents=query,
                QueryText=text,
                Filter={"IncludeCountries": ["IND"]},
                MaxResults=10,
                IntendedUse="Storage",
                Language="en",
            )


def _google_component(result, component_type):
    for component in result.get("address_components") or []:
        if component_type in (component.get("types") or []):
            return component
    return {}


def _google_text(result, *component_types, short=False):
    field = "short_name" if short else "long_name"
    for component_type in component_types:
        value = _google_component(result, component_type).get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _google_place_type(result):
    location_type = (result.get("geometry") or {}).get("location_type")
    if result.get("partial_match") is True:
        return "Other"
    if location_type == "ROOFTOP":
        return "PointAddress"
    if location_type == "RANGE_INTERPOLATED":
        return "InterpolatedAddress"
    return "Other"


def normalize_google_result(result):
    """Map a Google result into the existing private provider-neutral shape."""
    geometry = result.get("geometry") or {}
    location = geometry.get("location") or {}
    latitude, longitude = location.get("lat"), location.get("lng")
    country_code = _google_text(result, "country", short=True)
    country = {
        "Code2": country_code,
        "Code3": "IND" if country_code == "IN" else None,
        "Name": _google_text(result, "country"),
    }
    address = {
        "Country": country,
        "Region": {
            "Code": _google_text(result, "administrative_area_level_1", short=True),
            "Name": _google_text(result, "administrative_area_level_1"),
        },
        "Locality": _google_text(
            result,
            "locality",
            "postal_town",
            "administrative_area_level_2",
        ),
        "PostalCode": _google_text(result, "postal_code"),
        "Street": _google_text(result, "route"),
        "AddressNumber": _google_text(result, "street_number"),
    }
    return {
        "PlaceType": _google_place_type(result),
        "EstimatedPointAddress": result.get("partial_match") is True,
        "Position": [longitude, latitude],
        "Address": address,
    }


def _google_coordinates_present(result):
    location = (result.get("geometry") or {}).get("location") or {}
    latitude, longitude = location.get("lat"), location.get("lng")
    return all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        for value in (latitude, longitude)
    ) and (-90 <= latitude <= 90 and -180 <= longitude <= 180)


class GoogleAddressGeocoder:
    provider_name = GOOGLE_PROVIDER

    def __init__(
        self,
        *,
        api_key,
        street_unavailable_radius_m=STREET_UNAVAILABLE_RADIUS_M,
        client_factory=None,
    ):
        self._api_key = api_key
        self.street_unavailable_radius_m = street_unavailable_radius_m
        self._client_factory = client_factory or httpx.AsyncClient

    def _secret(self):
        value = (
            self._api_key.get_secret_value()
            if hasattr(self._api_key, "get_secret_value")
            else self._api_key
        )
        if not isinstance(value, str) or not value.strip():
            raise ServiceUnavailableError("Address lookup is temporarily unavailable")
        return value

    async def _request(self, params):
        request_params = {**params, "key": self._secret(), "language": "en"}
        timeout = httpx.Timeout(connect=5, read=15, write=5, pool=5)
        operation = "geocode" if "address" in params else "reverse_geocode"
        correlation_id = uuid4().hex
        try:
            with places_call(operation, self.provider_name):
                async with self._client_factory(
                    timeout=timeout,
                    follow_redirects=False,
                ) as client:
                    response = await client.get(
                        GOOGLE_GEOCODING_URL,
                        params=request_params,
                        headers={"Accept": "application/json"},
                    )
                    http_status = response.status_code
                    if http_status in {401, 403}:
                        raise GoogleDiagnosticFailure(
                            "GOOGLE_GEOCODE_AUTH_FAILURE", http_status=http_status
                        )
                    if http_status == 429:
                        raise GoogleDiagnosticFailure(
                            "GOOGLE_GEOCODE_QUOTA_OR_RATE_LIMIT", http_status=http_status
                        )
                    if 400 <= http_status <= 499:
                        raise GoogleDiagnosticFailure(
                            "GOOGLE_GEOCODE_PROVIDER_4XX", http_status=http_status
                        )
                    if 500 <= http_status <= 599:
                        raise GoogleDiagnosticFailure(
                            "GOOGLE_GEOCODE_PROVIDER_5XX", http_status=http_status
                        )
                    try:
                        payload = response.json()
                    except Exception:
                        raise GoogleDiagnosticFailure(
                            "GOOGLE_GEOCODE_MALFORMED_RESPONSE", http_status=http_status
                        ) from None
                if not isinstance(payload, dict):
                    raise GoogleDiagnosticFailure(
                        "GOOGLE_GEOCODE_MALFORMED_RESPONSE", http_status=http_status
                    )
                status = payload.get("status")
                if status == "ZERO_RESULTS":
                    result = GoogleProviderResult(
                        [], correlation_id, http_status, status, 0, False
                    )
                    log_google_geocode_diagnostic(
                        operation=operation,
                        reason="GOOGLE_GEOCODE_ZERO_RESULTS",
                        correlation_id=correlation_id,
                        http_status=http_status,
                        google_status=status,
                        result_count=0,
                    )
                    return result
                if status == "REQUEST_DENIED":
                    raise GoogleDiagnosticFailure(
                        "GOOGLE_GEOCODE_AUTH_FAILURE",
                        http_status=http_status,
                        google_status=status,
                    )
                if status == "OVER_QUERY_LIMIT":
                    raise GoogleDiagnosticFailure(
                        "GOOGLE_GEOCODE_QUOTA_OR_RATE_LIMIT",
                        http_status=http_status,
                        google_status=status,
                    )
                if status == "UNKNOWN_ERROR":
                    raise GoogleDiagnosticFailure(
                        "GOOGLE_GEOCODE_PROVIDER_5XX",
                        http_status=http_status,
                        google_status=status,
                    )
                results = payload.get("results")
                if status != "OK" or not isinstance(results, list):
                    reason = (
                        "GOOGLE_GEOCODE_PROVIDER_4XX"
                        if status == "INVALID_REQUEST"
                        else "GOOGLE_GEOCODE_MALFORMED_RESPONSE"
                    )
                    raise GoogleDiagnosticFailure(
                        reason,
                        http_status=http_status,
                        google_status=status,
                    )
                if not all(isinstance(result, dict) for result in results):
                    raise GoogleDiagnosticFailure(
                        "GOOGLE_GEOCODE_MALFORMED_RESPONSE",
                        http_status=http_status,
                        google_status=status,
                        result_count=len(results),
                    )
                coordinates_present = any(
                    _google_coordinates_present(result) for result in results
                )
                if results and not coordinates_present:
                    raise GoogleDiagnosticFailure(
                        "GOOGLE_GEOCODE_MISSING_COORDINATES",
                        http_status=http_status,
                        google_status=status,
                        result_count=len(results),
                    )
                try:
                    items = [normalize_google_result(result) for result in results]
                except Exception:
                    raise GoogleDiagnosticFailure(
                        "GOOGLE_GEOCODE_NORMALIZATION_FAILURE",
                        http_status=http_status,
                        google_status=status,
                        result_count=len(results),
                        coordinates_present=coordinates_present,
                    ) from None
                return GoogleProviderResult(
                    items,
                    correlation_id,
                    http_status,
                    status,
                    len(results),
                    coordinates_present,
                )
        except GoogleDiagnosticFailure as exc:
            log_google_geocode_diagnostic(
                operation=operation,
                reason=exc.reason,
                correlation_id=correlation_id,
                http_status=exc.http_status,
                google_status=exc.google_status,
                result_count=exc.result_count,
                coordinates_present=exc.coordinates_present,
            )
            raise ServiceUnavailableError("Address lookup is temporarily unavailable") from None
        except httpx.TimeoutException:
            log_google_geocode_diagnostic(
                operation=operation,
                reason="GOOGLE_GEOCODE_TIMEOUT",
                correlation_id=correlation_id,
            )
            raise ServiceUnavailableError("Address lookup is temporarily unavailable") from None
        except httpx.RequestError:
            log_google_geocode_diagnostic(
                operation=operation,
                reason="GOOGLE_GEOCODE_NETWORK_FAILURE",
                correlation_id=correlation_id,
            )
            raise ServiceUnavailableError("Address lookup is temporarily unavailable") from None
        except Exception:
            log_google_geocode_diagnostic(
                operation=operation,
                reason="GOOGLE_GEOCODE_INTERNAL_FAILURE",
                correlation_id=correlation_id,
            )
            raise ServiceUnavailableError("Address lookup is temporarily unavailable") from None

    async def geocode(self, address):
        query = query_components(address)
        provider_result = await self._request(
            {
                "address": query_text(address),
                "components": "country:IN",
            }
        )
        items = provider_result.items
        decision = evaluate_targets(
            items,
            query,
            street_unavailable_radius_m=self.street_unavailable_radius_m,
        )
        metadata = asdict(decision)
        metadata.update(provider=self.provider_name, policy_version=POLICY_VERSION)
        if not decision.eligible:
            if provider_result.google_status != "ZERO_RESULTS":
                log_google_geocode_diagnostic(
                    operation="geocode",
                    reason="GOOGLE_GEOCODE_POLICY_INELIGIBLE",
                    correlation_id=provider_result.correlation_id,
                    http_status=provider_result.http_status,
                    google_status=provider_result.google_status,
                    result_count=provider_result.result_count,
                    coordinates_present=provider_result.coordinates_present,
                )
            return metadata, None
        log_google_geocode_diagnostic(
            operation="geocode",
            reason="GOOGLE_GEOCODE_SUCCESS",
            correlation_id=provider_result.correlation_id,
            http_status=provider_result.http_status,
            google_status=provider_result.google_status,
            result_count=provider_result.result_count,
            coordinates_present=provider_result.coordinates_present,
            normalized_result_eligible=True,
        )
        chosen = items[decision.selected_index]
        private = {
            "position": chosen["Position"],
            "normalized_address": {
                key: chosen.get("Address", {}).get(key)
                for key in (
                    "Country",
                    "Region",
                    "Locality",
                    "PostalCode",
                    "Street",
                    "AddressNumber",
                )
            },
        }
        return metadata, private

    async def confirm_area(self, address, representative):
        try:
            latitude, longitude = representative
            provider_result = await self._request(
                {
                    "latlng": f"{latitude},{longitude}",
                    "result_type": "street_address",
                }
            )
            return precise_area_decision(address, provider_result.items)
        except Exception:
            raise ServiceUnavailableError("Address area confirmation is unavailable") from None


def build_address_geocoder(settings):
    provider = settings.permanent_address_geocoder_provider
    if provider == AMAZON_PROVIDER:
        return AmazonAddressGeocoder(
            region=settings.permanent_address_places_region,
            street_unavailable_radius_m=settings.permanent_address_street_unavailable_radius_m,
        )
    if provider == GOOGLE_PROVIDER:
        return GoogleAddressGeocoder(
            api_key=settings.google_geocoding_api_key,
            street_unavailable_radius_m=settings.permanent_address_street_unavailable_radius_m,
        )
    raise ServiceUnavailableError("Address verification is temporarily unavailable")
