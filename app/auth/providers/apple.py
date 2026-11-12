"""Native Sign in with Apple identity validation and token lifecycle."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import jwt
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError

from app.config import Settings

_ISSUER = "https://appleid.apple.com"
_JWKS_URL = f"{_ISSUER}/auth/keys"
_TOKEN_URL = f"{_ISSUER}/auth/token"
_REVOKE_URL = f"{_ISSUER}/auth/revoke"


class AppleIdentityValidationError(ValueError):
    """A privacy-safe reason for a rejected Apple credential."""

    def __init__(self, reason: str) -> None:
        super().__init__("Apple identity validation failed")
        self.safe_reason = reason


@dataclass(frozen=True)
class AppleIdentity:
    provider_user_id: str
    email: str


@dataclass(frozen=True)
class AppleTokenExchange:
    refresh_token: str


def _required(value: str | None, reason: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AppleIdentityValidationError(reason)
    return value.strip()


def _client_secret(settings: Settings) -> str:
    team_id = _required(settings.apple_team_id, "configuration_missing")
    key_id = _required(settings.apple_key_id, "configuration_missing")
    client_id = _required(settings.apple_client_id, "configuration_missing")
    if settings.apple_private_key is None:
        raise AppleIdentityValidationError("configuration_missing")
    private_key = settings.apple_private_key.get_secret_value().replace("\\n", "\n")
    now = datetime.now(tz=UTC)
    return jwt.encode(
        {
            "iss": team_id,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(days=180)).timestamp()),
            "aud": _ISSUER,
            "sub": client_id,
        },
        private_key,
        algorithm="ES256",
        headers={"kid": key_id},
    )


def validate_identity_token(
    identity_token: str,
    raw_nonce: str,
    settings: Settings,
) -> AppleIdentity:
    client_id = _required(settings.apple_client_id, "configuration_missing")
    expected_nonce = hashlib.sha256(raw_nonce.encode("utf-8")).hexdigest()
    try:
        signing_key = PyJWKClient(_JWKS_URL).get_signing_key_from_jwt(identity_token)
        claims = jwt.decode(
            identity_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=_ISSUER,
            options={"require": ["exp", "iss", "aud", "sub", "email", "email_verified", "nonce"]},
        )
    except InvalidTokenError as exc:
        raise AppleIdentityValidationError("identity_token_invalid") from exc

    if claims.get("nonce") != expected_nonce:
        raise AppleIdentityValidationError("nonce_invalid")
    if claims.get("email_verified") not in {True, "true"}:
        raise AppleIdentityValidationError("email_not_verified")
    subject = _required(claims.get("sub"), "subject_invalid")
    email = _required(claims.get("email"), "email_invalid")
    return AppleIdentity(provider_user_id=subject, email=email)


async def exchange_authorization_code(code: str, settings: Settings) -> AppleTokenExchange:
    client_id = _required(settings.apple_client_id, "configuration_missing")
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            _TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": _client_secret(settings),
                "code": code,
                "grant_type": "authorization_code",
            },
        )
    if response.status_code != 200:
        raise AppleIdentityValidationError("authorization_code_invalid")
    refresh_token = response.json().get("refresh_token")
    return AppleTokenExchange(refresh_token=_required(refresh_token, "refresh_token_missing"))


async def revoke_refresh_token(refresh_token: str, settings: Settings) -> None:
    client_id = _required(settings.apple_client_id, "configuration_missing")
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            _REVOKE_URL,
            data={
                "client_id": client_id,
                "client_secret": _client_secret(settings),
                "token": refresh_token,
                "token_type_hint": "refresh_token",
            },
        )
    if response.status_code != 200:
        raise AppleIdentityValidationError("token_revocation_failed")
