"""Backend-only geocoding and context-bound target encryption."""

import asyncio
import json
import math
import os
from dataclasses import asdict

import boto3
import httpx
from botocore.config import Config
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.exceptions import ServiceUnavailableError
from app.integrations.digilocker.crypto import parse_keyring
from app.logging.places import places_call
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
        try:
            operation = "geocode" if "address" in params else "reverse_geocode"
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
                    response.raise_for_status()
                    payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Malformed provider response")
                status = payload.get("status")
                if status == "ZERO_RESULTS":
                    return []
                results = payload.get("results")
                if status != "OK" or not isinstance(results, list):
                    raise ValueError("Provider request was not successful")
                if not all(isinstance(result, dict) for result in results):
                    raise ValueError("Malformed provider results")
                return [normalize_google_result(result) for result in results]
        except Exception:
            raise ServiceUnavailableError("Address lookup is temporarily unavailable") from None

    async def geocode(self, address):
        query = query_components(address)
        items = await self._request(
            {
                "address": query_text(address),
                "components": "country:IN",
            }
        )
        decision = evaluate_targets(
            items,
            query,
            street_unavailable_radius_m=self.street_unavailable_radius_m,
        )
        metadata = asdict(decision)
        metadata.update(provider=self.provider_name, policy_version=POLICY_VERSION)
        if not decision.eligible:
            return metadata, None
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
            items = await self._request(
                {
                    "latlng": f"{latitude},{longitude}",
                    "result_type": "street_address",
                }
            )
            return precise_area_decision(address, items)
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
