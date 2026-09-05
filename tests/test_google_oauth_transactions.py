"""Security contracts for one-time Google OAuth state and App Link handoffs."""

from __future__ import annotations

import json

import pytest

from app.auth.oauth_transactions import OAuthHandoffStore, OAuthTransactionStore
from app.config import Settings
from app.infrastructure.redis.keys import RedisKeys


class _MemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value
        self.ttls[key] = ex

    async def eval(self, _script: str, _keys: int, key: str) -> str | None:
        self.ttls.pop(key, None)
        return self.values.pop(key, None)


def _settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        jwt_secret_key="test-jwt-secret-key-32-chars-minimum!!",
    )


@pytest.mark.asyncio
async def test_google_state_is_random_pkce_bound_and_single_use() -> None:
    redis = _MemoryRedis()
    store = OAuthTransactionStore(redis, RedisKeys(_settings()))

    first = await store.create()
    second = await store.create()

    assert first.state != second.state
    assert first.code_verifier != second.code_verifier
    assert OAuthTransactionStore.code_challenge(first.code_verifier)
    key = next(key for key in redis.values if first.state in key)
    assert redis.ttls[key] == 300
    assert (await store.consume(first.state)).code_verifier == first.code_verifier
    with pytest.raises(ValueError, match="invalid or expired"):
        await store.consume(first.state)


@pytest.mark.asyncio
async def test_google_handoff_is_opaque_and_replay_safe() -> None:
    redis = _MemoryRedis()
    store = OAuthHandoffStore(redis, RedisKeys(_settings()))
    code = await store.create({"outcome": "PHONE_VERIFICATION_REQUIRED", "signup": {"id": "safe"}})

    key = next(key for key in redis.values if code in key)
    assert redis.ttls[key] == 120
    assert "access_token" not in code
    assert "refresh_token" not in code
    assert "@" not in code
    assert json.loads(redis.values[key])["outcome"] == "PHONE_VERIFICATION_REQUIRED"
    assert (await store.consume(code))["outcome"] == "PHONE_VERIFICATION_REQUIRED"
    with pytest.raises(ValueError, match="invalid or expired"):
        await store.consume(code)
