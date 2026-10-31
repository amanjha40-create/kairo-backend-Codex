"""Short-lived, one-time OAuth and App Link handoff records in Redis."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass

from redis.asyncio import Redis

from app.infrastructure.redis.keys import RedisKeys

_TTL_SECONDS = 300
_HANDOFF_TTL_SECONDS = 120
ANDROID_PRODUCTION_CLIENT = "android_production"
ANDROID_QA_CLIENT = "android_qa"
GOOGLE_OAUTH_CLIENT_TARGETS = frozenset({ANDROID_PRODUCTION_CLIENT, ANDROID_QA_CLIENT})
_CONSUME = """
local value = redis.call('GET', KEYS[1])
if not value then return nil end
redis.call('DEL', KEYS[1])
return value
"""


@dataclass(frozen=True)
class OAuthTransaction:
    state: str
    code_verifier: str
    client_target: str


class OAuthTransactionStore:
    def __init__(self, redis: Redis, keys: RedisKeys) -> None:
        self._redis = redis
        self._keys = keys

    async def create(self, *, client_target: str = ANDROID_PRODUCTION_CLIENT) -> OAuthTransaction:
        if client_target not in GOOGLE_OAUTH_CLIENT_TARGETS:
            raise ValueError("OAuth client target is invalid")
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        payload = json.dumps({"v": verifier, "t": client_target})
        await self._redis.set(
            self._keys.cache(domain="oauth-google", key=state),
            payload,
            ex=_TTL_SECONDS,
        )
        return OAuthTransaction(
            state=state,
            code_verifier=verifier,
            client_target=client_target,
        )

    @staticmethod
    def code_challenge(verifier: str) -> str:
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    async def consume(self, state: str) -> OAuthTransaction:
        raw = await self._redis.eval(
            _CONSUME,
            1,
            self._keys.cache(domain="oauth-google", key=state),
        )
        if raw is None:
            raise ValueError("OAuth transaction is invalid or expired")
        data = json.loads(raw)
        verifier = data.get("v")
        client_target = data.get("t", ANDROID_PRODUCTION_CLIENT)
        if (
            not isinstance(verifier, str)
            or not verifier
            or client_target not in GOOGLE_OAUTH_CLIENT_TARGETS
        ):
            raise ValueError("OAuth transaction is invalid or expired")
        return OAuthTransaction(
            state=state,
            code_verifier=verifier,
            client_target=client_target,
        )


class OAuthHandoffStore:
    def __init__(self, redis: Redis, keys: RedisKeys) -> None:
        self._redis = redis
        self._keys = keys

    async def create(self, payload: dict[str, object]) -> str:
        code = secrets.token_urlsafe(32)
        await self._redis.set(
            self._keys.cache(domain="oauth-google-handoff", key=code),
            json.dumps(payload),
            ex=_HANDOFF_TTL_SECONDS,
        )
        return code

    async def consume(
        self,
        code: str,
        *,
        expected_client_target: str = ANDROID_PRODUCTION_CLIENT,
    ) -> dict[str, object]:
        if expected_client_target not in GOOGLE_OAUTH_CLIENT_TARGETS:
            raise ValueError("Authentication handoff is invalid or expired")
        raw = await self._redis.eval(
            _CONSUME, 1, self._keys.cache(domain="oauth-google-handoff", key=code)
        )
        if raw is None:
            raise ValueError("Authentication handoff is invalid or expired")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Authentication handoff is invalid or expired")
        client_target = data.get("client_target", ANDROID_PRODUCTION_CLIENT)
        if client_target != expected_client_target:
            raise ValueError("Authentication handoff is invalid or expired")
        return data
