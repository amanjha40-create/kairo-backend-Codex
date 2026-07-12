"""Signup OTP generation, Redis storage, and rate limiting."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis

from app.config import Settings
from app.core.constants import SIGNUP_OTP_PURPOSE
from app.exceptions import RateLimitError
from app.infrastructure.redis.keys import RedisKeys


def generate_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def verify_otp_code(code: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_otp_code(code), stored_hash)


class SignupOtpStore:
    """Redis-backed OTP and send-rate limits for staged signup channels."""

    def __init__(self, redis: Redis, settings: Settings) -> None:
        self._redis = redis
        self._settings = settings
        self._keys = RedisKeys(settings)

    def _otp_key(self, signup_session_id: UUID, channel: str) -> str:
        return self._keys.otp(
            purpose=f"{SIGNUP_OTP_PURPOSE}:{channel}",
            subject=str(signup_session_id),
        )

    def _send_rate_key(self, signup_session_id: UUID, channel: str) -> str:
        return self._keys.rate_limit(
            bucket=f"signup_otp_send:{channel}",
            identifier=str(signup_session_id),
        )

    async def store_otp(self, signup_session_id: UUID, channel: str, code: str) -> None:
        ttl = self._settings.signup_otp_ttl_seconds
        await self._redis.set(self._otp_key(signup_session_id, channel), hash_otp_code(code), ex=ttl)

    async def verify_and_consume(self, signup_session_id: UUID, channel: str, code: str) -> bool:
        """Atomically verify and consume OTP via Lua — prevents two concurrent
        requests both passing the check before either deletes the key."""

        key = self._otp_key(signup_session_id, channel)
        expected_hash = hash_otp_code(code)
        # Lua: fetch stored hash, return 0 if missing/mismatch, delete + return 1 if match.
        _LUA_VERIFY_CONSUME = """
local stored = redis.call('GET', KEYS[1])
if stored == false then return 0 end
if stored ~= ARGV[1] then return 0 end
redis.call('DEL', KEYS[1])
return 1
"""
        result = await self._redis.eval(_LUA_VERIFY_CONSUME, 1, key, expected_hash)
        return bool(result)

    async def clear(self, signup_session_id: UUID, channel: str) -> None:
        await self._redis.delete(self._otp_key(signup_session_id, channel))

    async def clear_all(self, signup_session_id: UUID) -> None:
        await self._redis.delete(
            self._otp_key(signup_session_id, "email"),
            self._otp_key(signup_session_id, "phone"),
        )

    async def enforce_send_rate(self, signup_session_id: UUID, channel: str) -> None:
        """Hourly send cap across start + resend.

        Uses a Lua script to atomically INCR and set the TTL on the first
        increment — prevents a crash between INCR and EXPIRE leaving the
        counter key without an expiry (permanent lockout).
        """

        key = self._send_rate_key(signup_session_id, channel)
        _LUA_INCR_WITH_TTL = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], 3600) end
return count
"""
        count = await self._redis.eval(_LUA_INCR_WITH_TTL, 1, key)
        if count > self._settings.signup_otp_max_sends_per_hour:
            ttl = await self._redis.ttl(key)
            raise RateLimitError(
                "Too many verification codes sent. Try again later.",
                retry_after_seconds=max(ttl, 1),
            )

    def seconds_until_resend_allowed(self, last_sent_at: datetime | None) -> int:
        if last_sent_at is None:
            return 0
        elapsed = (datetime.now(tz=UTC) - last_sent_at).total_seconds()
        remaining = self._settings.signup_otp_resend_cooldown_seconds - int(elapsed)
        return max(remaining, 0)

    def assert_resend_allowed(self, last_sent_at: datetime | None) -> None:
        wait = self.seconds_until_resend_allowed(last_sent_at)
        if wait > 0:
            raise RateLimitError(
                "Please wait before requesting another code.",
                retry_after_seconds=wait,
            )
