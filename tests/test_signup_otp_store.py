"""Regression coverage for Redis-cluster-safe signup OTP cleanup."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.auth.signup_otp import SignupOtpStore
from app.config import Settings


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        jwt_secret_key="test-jwt-secret-key-32-chars-minimum!!",
        app_env="staging",
    )


@pytest.mark.asyncio
async def test_clear_all_deletes_otp_keys_individually_for_redis_cluster() -> None:
    redis = AsyncMock()
    store = SignupOtpStore(redis, _settings())  # type: ignore[arg-type]
    session_id = uuid4()

    await store.clear_all(session_id)

    assert redis.delete.await_count == 2
    assert all(len(call.args) == 1 for call in redis.delete.await_args_list)
    deleted_keys = {call.args[0] for call in redis.delete.await_args_list}
    assert any(":email:" in key for key in deleted_keys)
    assert any(":phone:" in key for key in deleted_keys)
