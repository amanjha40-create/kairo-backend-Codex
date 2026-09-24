"""Bounded user-bound PKCE transactions. Redis failures never fall back to process memory."""

import base64
import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import SecretStr
from redis.exceptions import RedisError

from app.infrastructure.redis.keys import RedisKeys

TTL_SECONDS = 600
_CREATE = """
if #ARGV ~= 4 or (#KEYS ~= 2 and #KEYS ~= 3) then return 0 end
if (ARGV[1] == '' and #KEYS ~= 2) or (ARGV[1] ~= '' and #KEYS ~= 3) then
    return 0
end
local old = redis.call('GET', KEYS[1])
if (old or '') ~= ARGV[1] then return 0 end
if old then redis.call('DEL', KEYS[3]) end
redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[4])
redis.call('SET', KEYS[2], ARGV[3], 'EX', ARGV[4])
return 1
"""
_CONSUME = """
local value = redis.call('GET', KEYS[1])
if value then redis.call('DEL', KEYS[1]) end
return value
"""
_CLEAR = """
if #ARGV ~= 1 or (#KEYS ~= 1 and #KEYS ~= 2) then return 0 end
if (ARGV[1] == '' and #KEYS ~= 1) or (ARGV[1] ~= '' and #KEYS ~= 2) then
    return 0
end
local old = redis.call('GET', KEYS[1])
if (old or '') ~= ARGV[1] then return 0 end
if old then redis.call('DEL', KEYS[2]) end
redis.call('DEL', KEYS[1])
return 1
"""


class StateError(Exception):
    def __init__(self, category="callback_invalid"):
        self.category = category
        super().__init__("DigiLocker authorization is invalid or expired")


@dataclass(frozen=True, repr=False)
class Transaction:
    state: SecretStr
    verifier: SecretStr
    user_id: UUID
    connection_id: UUID
    attempt_id: UUID
    created_at: datetime
    expires_at: datetime

    @property
    def challenge(self):
        digest = hashlib.sha256(self.verifier.get_secret_value().encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class TransactionStore:
    def __init__(self, redis, settings):
        self.redis = redis
        keys = RedisKeys(settings)
        self.prefix = keys.cache(domain="digilocker-tx-v1", key="")
        self.route_prefix = keys.cache(domain="digilocker-route-v1", key="")
        if "{" in self.prefix or "}" in self.prefix:
            raise RedisError("Invalid DigiLocker routing namespace")

    @staticmethod
    def _hex(value):
        if isinstance(value, bytes):
            value = value.decode("ascii")
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("Invalid routing fingerprint")
        return value

    @staticmethod
    def _fingerprint(state):
        return hashlib.sha256(state.encode("ascii")).hexdigest()

    def _routing_tag(self, user_id):
        return hashlib.sha256(
            b"kairoid:digilocker:owner-route:v1\0"
            + self.prefix.encode("utf-8")
            + b"\0"
            + user_id.bytes
        ).hexdigest()

    def _locator_key(self, fingerprint):
        return self.route_prefix + self._hex(fingerprint)

    def _owner_key(self, routing_tag):
        return self.prefix + "{" + self._hex(routing_tag) + "}:owner"

    def _state_key(self, routing_tag, fingerprint):
        return self.prefix + "{" + self._hex(routing_tag) + "}:state:" + self._hex(fingerprint)

    async def _owner_snapshot(self, owner_key):
        try:
            raw = await self.redis.get(owner_key)
            if raw is None:
                return ""
            return self._hex(raw)
        except ValueError:
            raise RedisError("Invalid DigiLocker owner pointer") from None

    async def create(self, user_id, connection_id, attempt_id, now):
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        fingerprint = self._fingerprint(state)
        routing_tag = self._routing_tag(user_id)
        expires = now + timedelta(seconds=TTL_SECONDS)
        payload = json.dumps(
            {
                "user_id": str(user_id),
                "connection_id": str(connection_id),
                "attempt_id": str(attempt_id),
                "verifier": verifier,
                "created_at": now.timestamp(),
                "expires_at": expires.timestamp(),
            }
        )
        # Locator-first failure leaves only bounded routing metadata, never authorization.
        if not await self.redis.set(
            self._locator_key(fingerprint), routing_tag, nx=True, ex=TTL_SECONDS
        ):
            raise RedisError("DigiLocker routing locator unavailable")
        owner_key = self._owner_key(routing_tag)
        old = await self._owner_snapshot(owner_key)
        script_keys = [owner_key, self._state_key(routing_tag, fingerprint)]
        if old:
            script_keys.append(self._state_key(routing_tag, old))
        result = await self.redis.eval(
            _CREATE,
            len(script_keys),
            *script_keys,
            old,
            fingerprint,
            payload,
            TTL_SECONDS,
        )
        if result != 1:
            raise RedisError("DigiLocker owner pointer changed")
        return Transaction(
            SecretStr(state), SecretStr(verifier), user_id, connection_id, attempt_id, now, expires
        )

    async def consume(self, state, now):
        if not isinstance(state, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", state):
            raise StateError()
        fingerprint = self._fingerprint(state)
        try:
            route = await self.redis.get(self._locator_key(fingerprint))
            routing_tag = self._hex(route)
        except ValueError:
            raise StateError() from None
        raw = await self.redis.eval(_CONSUME, 1, self._state_key(routing_tag, fingerprint))
        if raw is None:
            raise StateError()
        try:
            data = json.loads(raw)
            verifier = data["verifier"]
            if not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier):
                raise ValueError()
            created = datetime.fromtimestamp(data["created_at"], UTC)
            expires = datetime.fromtimestamp(data["expires_at"], UTC)
            if expires <= now:
                raise StateError("callback_expired")
            if created > now or expires - created != timedelta(seconds=TTL_SECONDS):
                raise ValueError()
            user_id = UUID(data["user_id"])
            if self._routing_tag(user_id) != routing_tag:
                raise ValueError()
            return Transaction(
                SecretStr(state),
                SecretStr(verifier),
                user_id,
                UUID(data["connection_id"]),
                UUID(data["attempt_id"]),
                created,
                expires,
            )
        except (ValueError, TypeError, KeyError, OverflowError, AttributeError, OSError):
            raise StateError() from None

    async def clear(self, user_id):
        routing_tag = self._routing_tag(user_id)
        owner_key = self._owner_key(routing_tag)
        old = await self._owner_snapshot(owner_key)
        script_keys = [owner_key]
        if old:
            script_keys.append(self._state_key(routing_tag, old))
        if await self.redis.eval(_CLEAR, len(script_keys), *script_keys, old) != 1:
            raise RedisError("DigiLocker owner pointer changed")
        # Locators contain only pseudonymous routing metadata; their original TTL is retained.
