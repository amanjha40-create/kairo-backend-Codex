"""JWT access tokens and opaque refresh material."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from jwt.exceptions import InvalidTokenError

from app.config import Settings
from app.core.constants import ACCESS_TOKEN_TYPE


def hash_refresh_token(raw_token: str) -> str:
    """Store only SHA-256 of refresh token — raw token never persisted."""

    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_access_token(
    settings: Settings,
    *,
    subject: uuid.UUID,
    role: str,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Mint short-lived JWT access token."""

    now = datetime.now(tz=UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "type": ACCESS_TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_access_ttl_minutes)).timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(settings: Settings, token: str) -> dict[str, Any]:
    """Decode and validate JWT — raises jwt exceptions on failure."""

    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub"]},
    )


def decode_token_safe(settings: Settings, token: str) -> dict[str, Any] | None:
    """Return None on invalid token — use when probing."""

    try:
        return decode_token(settings, token)
    except InvalidTokenError:
        return None


def generate_opaque_refresh_raw() -> str:
    """Cryptographically strong opaque segment for refresh token material."""

    return secrets.token_urlsafe(48)
