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

from app.infrastructure.redis.keys import RedisKeys

TTL_SECONDS = 600
_CREATE = """
local old = redis.call('GET', KEYS[1])
if old then redis.call('DEL', ARGV[1] .. old) end
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
local old = redis.call('GET', KEYS[1])
if old then redis.call('DEL', ARGV[1] .. old) end
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
        self.prefix = keys.cache(domain="digilocker-state", key="")
        self.owner_prefix = keys.cache(domain="digilocker-owner", key="")

    async def create(self, user_id, connection_id, attempt_id, now):
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        fingerprint = hashlib.sha256(state.encode("ascii")).hexdigest()
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
        await self.redis.eval(
            _CREATE,
            2,
            self.owner_prefix + str(user_id),
            self.prefix + fingerprint,
            self.prefix,
            fingerprint,
            payload,
            TTL_SECONDS,
        )
        return Transaction(
            SecretStr(state), SecretStr(verifier), user_id, connection_id, attempt_id, now, expires
        )

    async def consume(self, state, now):
        if not isinstance(state, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", state):
            raise StateError()
        fingerprint = hashlib.sha256(state.encode("ascii")).hexdigest()
        raw = await self.redis.eval(_CONSUME, 1, self.prefix + fingerprint)
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
            return Transaction(
                SecretStr(state),
                SecretStr(verifier),
                UUID(data["user_id"]),
                UUID(data["connection_id"]),
                UUID(data["attempt_id"]),
                created,
                expires,
            )
        except (ValueError, TypeError, KeyError, OverflowError, AttributeError, OSError):
            raise StateError() from None

    async def clear(self, user_id):
        await self.redis.eval(_CLEAR, 1, self.owner_prefix + str(user_id), self.prefix)
