"""Backend-only geocoding and context-bound target encryption."""

import asyncio
import json
import math
import os
from dataclasses import asdict

import boto3
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
    def __init__(self, *, region="us-east-1", street_unavailable_radius_m=STREET_UNAVAILABLE_RADIUS_M):
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
            metadata.update(provider="amazon_location", policy_version=POLICY_VERSION)
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
