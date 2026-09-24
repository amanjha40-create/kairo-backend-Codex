"""Bounded, non-persistent DigiLocker document reads. No OAuth lifecycle operations."""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
from dataclasses import dataclass

import httpx
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.integrations.digilocker.crypto import parse_keyring
from app.integrations.digilocker.provider import ProviderError

HOST = "https://digilocker.meripehchaan.gov.in"
ISSUED_URL = HOST + "/public/oauth2/2/files/issued"
FILE_URL = HOST + "/public/oauth2/1/file/"
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_LIST_BYTES = 1024 * 1024
SUPPORTED_TYPES = {"PANCR", "DRVLC"}
MIMES = {"application/pdf", "application/xml", "text/xml", "image/jpeg", "image/png"}
logger = logging.getLogger(__name__)


def _text(value, limit=512):
    if not isinstance(value, str) or len(value) > limit:
        return None
    value = value.strip()
    if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return None
    return value


def normalize_items(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ProviderError("invalid_response")
    if len(payload["items"]) > 500:
        raise ProviderError("response_too_large")
    items, malformed = [], 0
    for raw in payload["items"]:
        if not isinstance(raw, dict):
            malformed += 1
            continue
        uri = _text(raw.get("uri"), 2048)
        doctype = _text(raw.get("doctype"), 32)
        issuerid = _text(raw.get("issuerid"), 128)
        # URIs are opaque issuer identifiers, never arbitrary URLs or endpoint paths.
        if not uri or not re.fullmatch(r"[A-Za-z0-9._:-]+", uri) or not doctype or not issuerid:
            malformed += 1
            continue
        mime = raw.get("mime", [])
        mime = [mime] if isinstance(mime, str) else mime
        if not isinstance(mime, list) or len(mime) > 10:
            malformed += 1
            continue
        mimes = sorted({m.lower() for m in mime if isinstance(m, str) and m.lower() in MIMES})
        items.append(
            {
                "name": _text(raw.get("name")),
                "type": _text(raw.get("type"), 32),
                "date": _text(raw.get("date"), 64),
                "mime": mimes,
                "uri": uri,
                "doctype": doctype,
                "issuerid": issuerid,
                "issuer": _text(raw.get("issuer")),
                "description": _text(raw.get("description")),
                "supported": doctype in SUPPORTED_TYPES and raw.get("type") == "file",
            }
        )
    return items, malformed


class DocumentReferences:
    """Opaque, ten-minute owner/connection/credential-bound references; no server storage."""

    def __init__(self, settings, connection, now):
        self.keys = parse_keyring(
            settings.digilocker_token_encryption_keys,
            settings.digilocker_token_encryption_active_key_id,
            settings.app_env.value,
        )
        self.active = settings.digilocker_token_encryption_active_key_id
        self.now = int(now.timestamp())
        credential = hashlib.sha256(
            json.dumps(connection.encrypted_access_token, sort_keys=True).encode()
        ).hexdigest()
        self.aad = json.dumps(
            [
                "kairoid:digilocker-document:v1",
                settings.app_env.value,
                str(connection.user_id),
                str(connection.id),
                credential,
            ]
        ).encode()

    def issue(self, item):
        nonce = secrets.token_bytes(12)
        data = json.dumps({"expires": self.now + 600, "item": item}, separators=(",", ":")).encode()
        ciphertext = AESGCM(self.keys[self.active]).encrypt(nonce, data, self.aad)
        return self.active + "." + base64.urlsafe_b64encode(nonce + ciphertext).decode()

    def open(self, reference):
        try:
            if not isinstance(reference, str) or not 1 <= len(reference) <= 16384:
                raise ValueError()
            key, encoded = reference.rsplit(".", 1)
            raw = base64.b64decode(encoded, altchars=b"-_", validate=True)
            data = json.loads(AESGCM(self.keys[key]).decrypt(raw[:12], raw[12:], self.aad))
            if not self.now < data["expires"] <= self.now + 600:
                raise ValueError()
            item = data["item"]
            if not item["supported"] or item["doctype"] not in SUPPORTED_TYPES:
                raise ValueError()
            return item
        except (ValueError, KeyError, TypeError, InvalidTag):
            raise ProviderError("invalid_reference") from None


@dataclass(repr=False)
class RetrievedDocument:
    content: bytes
    mime: str


class DigiLockerDocuments:
    def __init__(self, settings, *, client=None):
        self.settings = settings
        self.client = client

    async def _get(self, token, *, uri=None):
        operation = "file" if uri is not None else "issued"
        client = self.client or httpx.AsyncClient()
        status = None
        category = "NONE"
        try:
            async with (
                asyncio.timeout(20),
                client.stream(
                    "GET",
                FILE_URL + uri if uri is not None else ISSUED_URL,
                    headers={
                        "Authorization": "Bearer " + token.get_secret_value(),
                        "Accept-Encoding": "identity",
                    },
                    auth=None,
                    follow_redirects=False,
                    timeout=httpx.Timeout(15, connect=3, pool=3),
                ) as response,
            ):
                status = response.status_code
                if status != 200:
                    raise ProviderError(
                        {
                            401: "invalid_token",
                            403: "insufficient_scope",
                            404: "document_not_found",
                        }.get(status, "provider_unavailable")
                    )
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise ProviderError("invalid_response")
                limit = MAX_FILE_BYTES if uri is not None else MAX_LIST_BYTES
                data = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    if len(data) + len(chunk) > limit:
                        raise ProviderError("response_too_large")
                    data.extend(chunk)
                if uri is None:
                    try:
                        return normalize_items(json.loads(data))
                    except (ValueError, UnicodeError, RecursionError):
                        raise ProviderError("invalid_response") from None
                try:
                    encoded = response.headers.get("hmac", "")
                    if len(encoded) != 44:
                        raise ValueError()
                    expected = base64.b64decode(encoded, validate=True)
                except ValueError:
                    raise ProviderError("integrity_failed") from None
                actual = hmac.digest(
                    self.settings.digilocker_client_secret.get_secret_value().encode(),
                    data,
                    "sha256",
                )
                if not hmac.compare_digest(expected, actual):
                    raise ProviderError("integrity_failed")
                mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if not data or mime not in MIMES:
                    raise ProviderError("invalid_response")
                return RetrievedDocument(bytes(data), mime)
        except ProviderError as exc:
            category = exc.category
            raise
        except (httpx.HTTPError, TimeoutError):
            category = "transport_error"
            raise ProviderError(category) from None
        finally:
            logger.info(
                "digilocker_document_response",
                extra={"operation": operation, "provider_status": status, "category": category},
            )
            if self.client is None:
                await client.aclose()

    async def issued(self, token):
        return await self._get(token)

    async def retrieve(self, token, uri):
        return await self._get(token, uri=uri)
