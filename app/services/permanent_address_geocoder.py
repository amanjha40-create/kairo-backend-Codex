"""Backend-only geocoding and context-bound target encryption."""

import asyncio
import json
import logging
import math
import os
import re
from dataclasses import asdict

import boto3
from botocore.config import Config
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.exceptions import ServiceUnavailableError
from app.integrations.digilocker.crypto import parse_keyring
from app.services.permanent_address_quality import POLICY_VERSION, evaluate_targets

logger = logging.getLogger(__name__)


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
    query = {
        "Country": "IND",
        "Region": address["state"],
        "Locality": address["city"],
        "PostalCode": address["postal_code"],
    }
    line = address["address_line_1"]
    match = re.fullmatch(r"([0-9][\w/-]{0,30})\s+(.+)", line)
    if match:
        query["AddressNumber"], query["Street"] = match.groups()
    else:
        query["Street"] = line
    if address.get("locality"):
        query["District"] = address["locality"]
    return query


class AmazonAddressGeocoder:
    async def geocode(self, address):
        query = query_components(address)
        try:
            response = await asyncio.to_thread(self._request, query)
            items = response.get("ResultItems", [])
            decision = evaluate_targets(items, query)
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

    @staticmethod
    def _request(query):
        client = boto3.client(
            "geo-places",
            region_name="us-east-1",
            config=Config(connect_timeout=5, read_timeout=15, retries={"total_max_attempts": 1}),
        )
        logger.info("permanent_address.geocode_request", extra={"request_count": 1})
        return client.geocode(
            QueryComponents=query,
            Filter={"IncludeCountries": ["IND"]},
            MaxResults=10,
            IntendedUse="Storage",
            Language="en",
        )
