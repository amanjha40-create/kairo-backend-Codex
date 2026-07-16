"""Redis-backed rate limiting dependencies for sensitive endpoints."""

from __future__ import annotations

from fastapi import Depends, Request
from redis.asyncio import Redis

from app.config import Settings, get_settings
from app.exceptions import RateLimitError
from app.infrastructure.redis.deps import get_redis

# Lua: atomic INCR + set TTL on first call.  Returns current count.
_LUA_RATE = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return count
"""


async def _check_rate(
    redis: Redis,
    key: str,
    *,
    window_seconds: int,
    max_requests: int,
) -> None:
    count = await redis.eval(_LUA_RATE, 1, key, str(window_seconds))
    if count > max_requests:
        ttl = await redis.ttl(key)
        raise RateLimitError(
            "Too many requests — please slow down.",
            retry_after_seconds=max(int(ttl), 1),
        )


async def auth_rate_limit(
    request: Request,
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> None:
    """10 auth attempts per IP per 60 seconds.

    Applied to login, register, and OTP-verify endpoints.  Keyed by the
    connecting IP so it survives session restarts.
    """

    ip = request.client.host if request.client else "unknown"
    key = f"rate:auth:{ip}"
    await _check_rate(
        redis,
        key,
        window_seconds=settings.auth_rate_limit_window_seconds,
        max_requests=settings.auth_rate_limit_max_requests,
    )


async def otp_verify_rate_limit(
    request: Request,
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> None:
    """5 OTP verify attempts per IP per 60 seconds — tighter than the general
    auth limiter to protect against distributed OTP brute-force."""

    ip = request.client.host if request.client else "unknown"
    key = f"rate:otp_verify:{ip}"
    await _check_rate(
        redis,
        key,
        window_seconds=settings.otp_verify_rate_limit_window_seconds,
        max_requests=settings.otp_verify_rate_limit_max_requests,
    )
