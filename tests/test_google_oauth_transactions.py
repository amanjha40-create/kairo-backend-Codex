"""Security contracts for one-time Google OAuth state and App Link handoffs."""

from __future__ import annotations

import json

import pytest

from app.auth.oauth_transactions import (
    ANDROID_PRODUCTION_CLIENT,
    ANDROID_QA_CLIENT,
    OAuthHandoffStore,
    OAuthTransactionStore,
)
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
    assert first.client_target == ANDROID_PRODUCTION_CLIENT
    assert OAuthTransactionStore.code_challenge(first.code_verifier)
    key = next(key for key in redis.values if first.state in key)
    assert redis.ttls[key] == 300
    assert (await store.consume(first.state)).code_verifier == first.code_verifier
    with pytest.raises(ValueError, match="invalid or expired"):
        await store.consume(first.state)


@pytest.mark.asyncio
async def test_google_state_binds_qa_target_and_rejects_arbitrary_target() -> None:
    redis = _MemoryRedis()
    store = OAuthTransactionStore(redis, RedisKeys(_settings()))

    transaction = await store.create(client_target=ANDROID_QA_CLIENT)
    stored = json.loads(
        next(value for key, value in redis.values.items() if transaction.state in key)
    )
    assert stored == {"v": transaction.code_verifier, "t": ANDROID_QA_CLIENT}
    assert (await store.consume(transaction.state)).client_target == ANDROID_QA_CLIENT
    with pytest.raises(ValueError, match="client target is invalid"):
        await store.create(client_target="https://attacker.example")


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


@pytest.mark.asyncio
async def test_google_handoff_is_bound_to_client_and_wrong_client_consumes_it() -> None:
    redis = _MemoryRedis()
    store = OAuthHandoffStore(redis, RedisKeys(_settings()))
    code = await store.create(
        {
            "outcome": "LOGIN_COMPLETE",
            "client_target": ANDROID_QA_CLIENT,
        }
    )

    with pytest.raises(ValueError, match="invalid or expired"):
        await store.consume(code, expected_client_target=ANDROID_PRODUCTION_CLIENT)
    with pytest.raises(ValueError, match="invalid or expired"):
        await store.consume(code, expected_client_target=ANDROID_QA_CLIENT)


@pytest.mark.asyncio
async def test_expired_google_handoff_fails_closed() -> None:
    redis = _MemoryRedis()
    store = OAuthHandoffStore(redis, RedisKeys(_settings()))
    code = await store.create(
        {
            "outcome": "LOGIN_COMPLETE",
            "client_target": ANDROID_QA_CLIENT,
        }
    )
    key = next(key for key in redis.values if code in key)
    redis.values.pop(key)
    redis.ttls.pop(key)

    with pytest.raises(ValueError, match="invalid or expired"):
        await store.consume(code, expected_client_target=ANDROID_QA_CLIENT)
