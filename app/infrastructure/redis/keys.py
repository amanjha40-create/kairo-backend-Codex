"""Namespaced Redis keys — avoids collisions across envs and services."""

from __future__ import annotations

from app.config import Settings, get_settings


def build_key_prefix(settings: Settings | None = None) -> str:
    """Return prefix like ``kairo-backend:development:`` — trailing colon included."""

    s = settings or get_settings()
    if s.redis_key_prefix:
        base = s.redis_key_prefix.strip().rstrip(":")
    else:
        safe_name = s.app_name.lower().replace(" ", "_")
        base = f"{safe_name}:{s.app_env.value}"
    return f"{base}:"


class RedisKeys:
    """Typed key builders for common use cases (rate limit, OTP, cache)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._prefix = build_key_prefix(settings)

    def rate_limit(self, *, bucket: str, identifier: str) -> str:
        return f"{self._prefix}rl:{bucket}:{identifier}"

    def otp(self, *, purpose: str, subject: str) -> str:
        return f"{self._prefix}otp:{purpose}:{subject}"

    def cache(self, *, domain: str, key: str) -> str:
        return f"{self._prefix}cache:{domain}:{key}"

    def session_blocklist(self, *, jti_or_hash: str) -> str:
        return f"{self._prefix}session:block:{jti_or_hash}"
