"""Synthetic-only fixtures. No provider network or existing account credentials."""

import base64
import json
import secrets
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from pydantic import SecretStr

from app.config import Settings
from app.integrations.digilocker.provider import DigiLockerProvider, TokenGrant


def config_values():
    return dict(
        digilocker_enabled=True,
        digilocker_client_id="synthetic-client",
        digilocker_client_secret=SecretStr("synthetic-client-secret"),
        digilocker_authorize_url="https://provider.example.invalid/authorize",
        digilocker_token_url="https://provider.example.invalid/token",
        digilocker_revoke_url="https://provider.example.invalid/revoke",
        digilocker_redirect_uri="https://api.example.invalid/api/v1/integrations/digilocker/callback",
        digilocker_purpose="Synthetic credential verification",
        digilocker_service_name="Synthetic Test Service_24",
        digilocker_token_encryption_active_key_id="test-v1",
        digilocker_token_encryption_keys=SecretStr(
            json.dumps({"test-v1": base64.b64encode(secrets.token_bytes(32)).decode("ascii")})
        ),
    )


def settings(**overrides):
    values = config_values()
    values.update(overrides)
    return Settings(**values)


def grant(*, refresh=True, scopes=None, consent=None, expires=3600):
    return TokenGrant(
        SecretStr(secrets.token_urlsafe(32)),
        SecretStr(secrets.token_urlsafe(32)) if refresh else None,
        datetime.now(UTC) + timedelta(seconds=expires),
        consent,
        scopes if scopes is not None else ["files.issueddocs"],
    )


def provider(config):
    result = DigiLockerProvider(config)
    result.exchange_authorization_code = AsyncMock(return_value=grant())
    result.refresh_access_token = AsyncMock(return_value=grant())
    result.revoke_token = AsyncMock()
    return result
