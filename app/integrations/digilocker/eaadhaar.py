"""Dedicated, memory-only e-Aadhaar transport and minimized identity matching."""

import asyncio
import base64
import hashlib
import hmac
import io
import json
from xml.etree.ElementTree import ParseError

import httpx
from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import iterparse

from app.integrations.digilocker.identity import Match, _date, _match_diagnostics, normalize_name
from app.integrations.digilocker.provider import ProviderError

MAX_BODY = 1024 * 1024
MAX_USER_DETAILS = 64 * 1024


def verify_integrity(content, header, secret):
    try:
        if not isinstance(header, str) or len(header) != 44:
            raise ValueError()
        expected = base64.b64decode(header, validate=True)
        if len(expected) != 32 or base64.b64encode(expected).decode("ascii") != header:
            raise ValueError()
        if not hmac.compare_digest(
            expected, hmac.digest(secret.get_secret_value().encode("utf-8"), content, "sha256")
        ):
            raise ValueError()
    except (ValueError, UnicodeError):
        raise ProviderError("integrity_failed") from None


def match_xml(content, name, dob, today):
    """Private parser: caller must establish HMAC first. No extracted facts escape."""
    try:
        if not content or len(content) > MAX_BODY:
            raise ValueError()
        depth = count = 0
        root = None
        for event, node in iterparse(
            io.BytesIO(content),
            events=("start", "end"),
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        ):
            if event == "start":
                depth += 1
                count += 1
                if root is None:
                    root = node
                if depth > 16 or count > 256 or len(node.attrib) > 32:
                    raise ValueError()
                if node.tag.startswith("{http://www.w3.org/2001/XInclude}"):
                    raise ValueError()
                if any(len(k) > 128 or len(v) > 1024 for k, v in node.attrib.items()):
                    raise ValueError()
            else:
                depth -= 1
                # Photo is bounded by the body limit and discarded, never decoded.
                limit = MAX_BODY if node.tag == "Pht" else 8192
                if len(node.text or "") > limit or len(node.tail or "") > 8192:
                    raise ValueError()
        if root.tag not in {"AadhaarXmlSchema", "EaadharXamlSchema"}:
            raise ValueError()
        kycs = root.findall("KycRes")
        if len(kycs) != 1 or len(kycs[0].findall("UidData")) != 1:
            raise ValueError()
        people = kycs[0].findall("./UidData/Poi")
        if len(people) != 1 or len(list(root.iter("Poi"))) != 1:
            raise ValueError()

        # Only the documented identity child fields are read. Poa/LData/Pht/uid/tkn
        # and arbitrary extras never enter the matching result or persistence model.
        def field(key):
            nodes = people[0].findall(key)
            if len(nodes) != 1 or list(nodes[0]) or len(nodes[0].text or "") > 255:
                raise ValueError()
            return (nodes[0].text or "").strip()

        given = normalize_name(field("name"))
        birth = _date(field("dob"))
        if birth and birth > today:
            raise ValueError()
        diagnostic = _match_diagnostics(given, normalize_name(name), birth, dob)
        reason = diagnostic["mismatch_reason"]
        if reason in {"NAME_MISMATCH", "DOB_MISMATCH", "NAME_AND_DOB_MISMATCH"}:
            result = "MISMATCH"
        elif given and normalize_name(name) and birth and dob:
            result = "VERIFIED_MATCH"
        else:
            result = "PARTIAL_MATCH" if given or birth else "UNABLE_TO_VERIFY"
        return Match(result, diagnostics=diagnostic)
    except (ValueError, TypeError, ParseError, DefusedXmlException, RecursionError):
        raise ProviderError("invalid_response") from None


class DigiLockerEAadhaar:
    def __init__(self, settings, *, client=None):
        self.settings = settings
        self.client = client

    async def _get(self, token, *, aadhaar):
        client = self.client or httpx.AsyncClient()
        try:
            async with (
                asyncio.timeout(20),
                client.stream(
                    "GET",
                    self.settings.digilocker_eaadhaar_url
                    if aadhaar
                    else self.settings.digilocker_user_details_url,
                    headers={
                        "Authorization": "Bearer " + token.get_secret_value(),
                        "Accept": "application/xml" if aadhaar else "application/json",
                        "Accept-Encoding": "identity",
                    },
                    auth=None,
                    follow_redirects=False,
                    timeout=httpx.Timeout(15, connect=3, pool=3),
                ) as response,
            ):
                if response.status_code != 200:
                    # Do not read error bodies, which can contain personal fields.
                    raise ProviderError(
                        {
                            401: "invalid_token",
                            403: "insufficient_scope",
                            404: "aadhaar_not_linked" if aadhaar else "account_unavailable",
                        }.get(response.status_code, "provider_unavailable")
                    )
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise ProviderError("invalid_response")
                expected = "application/xml" if aadhaar else "application/json"
                if (
                    response.headers.get("content-type", "").split(";")[0].strip().lower()
                    != expected
                ):
                    raise ProviderError("invalid_response")
                data = bytearray()
                limit = MAX_BODY if aadhaar else MAX_USER_DETAILS
                async for chunk in response.aiter_raw():
                    if len(data) + len(chunk) > limit:
                        raise ProviderError("response_too_large")
                    data.extend(chunk)
                if aadhaar:
                    verify_integrity(
                        data, response.headers.get("hmac"), self.settings.digilocker_client_secret
                    )
                    return data
                try:
                    payload = json.loads(data)
                    flag = payload.get("eaadhaar") if isinstance(payload, dict) else None
                    if flag not in {"Y", "N"}:
                        raise ValueError()
                    return flag == "Y"
                except (ValueError, TypeError, UnicodeError, RecursionError):
                    raise ProviderError("invalid_response") from None
        except (httpx.HTTPError, TimeoutError):
            raise ProviderError("transport_error") from None
        finally:
            if self.client is None:
                await client.aclose()

    async def availability(self, token):
        return await self._get(token, aadhaar=False)

    async def verify(self, token, *, name, dob, today):
        data = await self._get(token, aadhaar=True)
        try:
            return match_xml(data, name, dob, today)
        finally:
            data[:] = b"\x00" * len(data)


def provenance_fingerprint(user_id):
    # Stable owner-scoped local reference; never a provider identifier or Aadhaar hash.
    return hashlib.sha256(f"digilocker:eaadhaar:owner:{user_id}".encode()).hexdigest()
