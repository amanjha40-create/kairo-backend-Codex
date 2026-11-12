"""Sign in with Apple remains nonce-bound and validates signed identity claims."""

from __future__ import annotations

import hashlib

import pytest

from app.auth.providers.apple import AppleIdentityValidationError, validate_identity_token
from app.config import Settings


def _settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        jwt_secret_key="test-jwt-secret-key-32-chars-minimum!!",
        apple_client_id="com.kairoid.Kairo",
    )


@pytest.mark.parametrize("relay_domain", ["privaterelay.appleid.com", "private.icloud.com"])
@pytest.mark.parametrize(
    "overrides,valid",
    [
        ({}, True),
        ({"sub": ""}, False),
        ({"email": ""}, False),
        ({"email_verified": False}, False),
        ({"nonce": "wrong"}, False),
    ],
)
def test_apple_signed_claims_and_nonce_are_validated(
    monkeypatch, relay_domain, overrides, valid
) -> None:
    import app.auth.providers.apple as module

    raw_nonce = "nonce-with-enough-entropy-for-a-test"
    claims = {
        "sub": "apple-stable-subject",
        "email": f"relay@{relay_domain}",
        "email_verified": True,
        "nonce": hashlib.sha256(raw_nonce.encode()).hexdigest(),
    }
    claims.update(overrides)
    monkeypatch.setattr(
        module.PyJWKClient,
        "get_signing_key_from_jwt",
        lambda *_args: type("Key", (), {"key": "key"})(),
    )
    monkeypatch.setattr(module.jwt, "decode", lambda *_args, **_kwargs: claims)

    if valid:
        identity = validate_identity_token("signed-token", raw_nonce, _settings())
        assert identity.provider_user_id == "apple-stable-subject"
        assert identity.email.endswith(f"@{relay_domain}")
    else:
        with pytest.raises(AppleIdentityValidationError):
            validate_identity_token("signed-token", raw_nonce, _settings())
