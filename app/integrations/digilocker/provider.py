"""Requester OAuth wire client. Identity payloads are deliberately discarded."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from pydantic import SecretStr

from app.integrations.digilocker.crypto import MAX_TOKEN_BYTES
from app.integrations.digilocker.diagnostics import ExchangeDiagnostics


class ProviderError(Exception):
    def __init__(self, category):
        self.category = category
        super().__init__("DigiLocker provider request failed")


@dataclass(frozen=True, repr=False)
class TokenGrant:
    access_token: SecretStr
    refresh_token: SecretStr | None
    expires_at: datetime
    consent_valid_until: datetime | None
    scopes: list[str] | None


def _token(value):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.encode("utf-8")) > MAX_TOKEN_BYTES
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ValueError()
    return SecretStr(value)


def parse_grant(data, now):
    try:
        if not isinstance(data, dict) or data.get("token_type", "").lower() != "bearer":
            raise ValueError()
        access = _token(data.get("access_token"))
        refresh = _token(data["refresh_token"]) if "refresh_token" in data else None
        expires = data.get("expires_in")
        if type(expires) is not int or not 1 <= expires <= 31_536_000:
            raise ValueError()
        consent = data.get("consent_valid_till")
        if consent is not None:
            if type(consent) is not int:
                raise ValueError()
            consent = datetime.fromtimestamp(consent, UTC)
            if consent <= now:
                raise ValueError()
        scopes = None
        if "scope" in data:
            if not isinstance(data["scope"], str) or len(data["scope"]) > 8192:
                raise ValueError()
            # Issued-document scopes can contain PAN/DL numbers. Never retain those.
            scopes = sorted(
                {
                    s
                    for s in data["scope"].split()
                    if re.fullmatch(
                        r"files\.(?:issueddocs|uploadeddocs)|[Uu]serdetails|openid|"
                        r"(?:partners\.|file\.partners/)[A-Z]{2,16}",
                        s,
                    )
                }
            )
        return TokenGrant(access, refresh, now + timedelta(seconds=expires), consent, scopes)
    except (ValueError, TypeError, AttributeError, OverflowError, OSError):
        raise ProviderError("invalid_response") from None


class DigiLockerProvider:
    def __init__(self, settings, *, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.client = client

    def build_authorization_url(self, *, state, challenge, now):
        s = self.settings
        params = dict(
            response_type="code",
            client_id=s.digilocker_client_id,
            redirect_uri=s.digilocker_redirect_uri,
            state=state,
            code_challenge=challenge,
            code_challenge_method="S256",
            purpose=s.digilocker_purpose,
            service_name=s.digilocker_service_name,
        )
        if s.digilocker_req_doctypes:
            params["req_doctype"] = s.digilocker_req_doctypes
        if s.digilocker_consent_ttl:
            params["consent_valid_till"] = int(now.timestamp()) + s.digilocker_consent_ttl
        return s.digilocker_authorize_url + "?" + urlencode(params)

    async def _post(self, url, data, *, revocation=False, diagnostics=None):
        client = self.client or httpx.AsyncClient()
        try:
            async with (
                asyncio.timeout(15),
                client.stream(
                    "POST",
                    url,
                    data=data,
                    auth=httpx.BasicAuth(
                        self.settings.digilocker_client_id,
                        self.settings.digilocker_client_secret.get_secret_value(),
                    ),
                    timeout=httpx.Timeout(10, connect=3, pool=3),
                    follow_redirects=False,
                    headers={"Accept": "application/json"},
                ) as response,
            ):
                if diagnostics is not None:
                    diagnostics.received(response)
                if revocation and response.status_code == 200:
                    return None
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 65_536:
                        if diagnostics is not None:
                            diagnostics.parse_category = "response_too_large"
                            diagnostics.failure = "RESPONSE_PARSE_ERROR"
                        raise ProviderError("invalid_response")
                import json

                try:
                    payload = json.loads(content)
                except (ValueError, UnicodeError, RecursionError):
                    if diagnostics is not None:
                        diagnostics.parse_category = "invalid_json"
                        diagnostics.failure = "RESPONSE_PARSE_ERROR"
                    raise ProviderError("invalid_response") from None
                if diagnostics is not None:
                    diagnostics.parsed(payload)
                if response.status_code != 200:
                    if (
                        response.status_code in {400, 401}
                        and isinstance(payload, dict)
                        and payload.get("error") == "invalid_grant"
                    ):
                        raise ProviderError("invalid_grant")
                    raise ProviderError("provider_unavailable")
                return payload
        except (httpx.HTTPError, TimeoutError) as exc:
            if diagnostics is not None:
                diagnostics.transport_error(exc)
            raise ProviderError("provider_unavailable") from None
        finally:
            if self.client is None:
                await client.aclose()

    async def exchange_authorization_code(self, code: SecretStr, verifier: SecretStr, *, now):
        data = {
            "grant_type": "authorization_code",
            "code": code.get_secret_value(),
            "redirect_uri": self.settings.digilocker_redirect_uri,
            "code_verifier": verifier.get_secret_value(),
        }
        diagnostics = ExchangeDiagnostics(
            self.settings.digilocker_token_url, data,
            client_id=self.settings.digilocker_client_id,
            client_secret=self.settings.digilocker_client_secret.get_secret_value(),
        )
        try:
            payload = await self._post(
                self.settings.digilocker_token_url, data, diagnostics=diagnostics
            )
            try:
                grant = parse_grant(payload, now)
            except ProviderError:
                diagnostics.schema_failure(payload)
                raise
            diagnostics.parse_category = "valid_token_response"
            return grant
        finally:
            diagnostics.finish()

    async def refresh_access_token(self, token: SecretStr, *, now):
        return parse_grant(
            await self._post(
                self.settings.digilocker_token_url,
                {
                    "grant_type": "refresh_token",
                    "refresh_token": token.get_secret_value(),
                },
            ),
            now,
        )

    async def revoke_token(self, token: SecretStr, purpose: str):
        await self._post(
            self.settings.digilocker_revoke_url,
            {
                "token": token.get_secret_value(),
                "token_type_hint": purpose,
            },
            revocation=True,
        )
