"""Google signed ID-token claim validation stays fail-closed."""

from __future__ import annotations

import pytest

from app.auth.providers.google import GoogleOAuthProvider
from app.config import Settings


class _Response:
    def raise_for_status(self) -> None: pass
    def json(self) -> dict[str, str]: return {"id_token": "signed-token"}


class _Client:
    async def __aenter__(self): return self
    async def __aexit__(self, *_args): return None
    async def post(self, *_args, **_kwargs): return _Response()


def _settings() -> Settings:
    return Settings(app_env="test", database_url="postgresql+asyncpg://kairo:kairo@localhost:5432/kairo", jwt_secret_key="test-jwt-secret-key-32-chars-minimum!!", google_client_id="staging-web-client", google_client_secret="not-a-real-secret", google_redirect_uri="https://staging-api.kairoid.com/api/v1/auth/google/callback")


@pytest.mark.asyncio
@pytest.mark.parametrize("claims,valid", [
    ({"sub": "google-sub", "email": "candidate@example.com", "email_verified": True}, True),
    ({"sub": "", "email": "candidate@example.com", "email_verified": True}, False),
    ({"sub": "google-sub", "email": "", "email_verified": True}, False),
    ({"sub": "google-sub", "email": "candidate@example.com", "email_verified": False}, False),
])
async def test_google_signed_claims_are_validated(monkeypatch, claims, valid) -> None:
    import app.auth.providers.google as module
    monkeypatch.setattr(module.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(module.PyJWKClient, "get_signing_key_from_jwt", lambda *_args: type("Key", (), {"key": "key"})())
    monkeypatch.setattr(module.jwt, "decode", lambda *_args, **_kwargs: claims)
    provider = GoogleOAuthProvider()
    if valid:
        assert (await provider.exchange_code("code", _settings())).provider_user_id == "google-sub"
    else:
        with pytest.raises(ValueError):
            await provider.exchange_code("code", _settings())
