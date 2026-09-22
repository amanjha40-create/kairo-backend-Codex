"""Context-bound credential envelopes. Keys are runtime-only, never derived."""

from __future__ import annotations

import base64
import binascii
import json
import re
import secrets
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

MAX_TOKEN_BYTES = 16_384
_KEY_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}\Z")


class KeyConfigurationError(RuntimeError):
    """Not ValueError: Settings must not embed raw configuration in a validation error."""

    def __init__(self) -> None:
        super().__init__("Invalid DigiLocker encryption key configuration")


class TokenCryptoError(Exception):
    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__("Provider credential could not be processed")


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise KeyConfigurationError()
        result[key] = value
    return result


def _decode(value: object, *, limit: int) -> bytes:
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError()
    raw = base64.b64decode(value, validate=True)
    if base64.b64encode(raw).decode("ascii") != value:
        raise ValueError()
    return raw


def parse_keyring(raw: SecretStr | None, active: str | None, environment: str) -> dict[str, bytes]:
    try:
        if raw is None or not isinstance(active, str) or not _KEY_ID.fullmatch(active):
            raise ValueError()
        value = raw.get_secret_value()
        if len(value) > 8192:
            raise ValueError()
        data = json.loads(value, object_pairs_hook=_unique_pairs)
        if not isinstance(data, dict) or not 1 <= len(data) <= 8 or active not in data:
            raise ValueError()
        keys = {}
        for key_id, encoded in data.items():
            if not _KEY_ID.fullmatch(key_id):
                raise ValueError()
            if environment in {"staging", "production"} and not key_id.startswith(
                environment + "-"
            ):
                raise ValueError()
            key = _decode(encoded, limit=44)
            if len(key) != 32 or key in keys.values():
                raise ValueError()
            keys[key_id] = key
        return keys
    except (
        ValueError,
        TypeError,
        AttributeError,
        RecursionError,
        binascii.Error,
        KeyConfigurationError,
    ):
        raise KeyConfigurationError() from None


class TokenCipher:
    """Single entry point for provider-token encryption; no plaintext cache or logging."""

    def __init__(self, keyring: SecretStr, active_key_id: str, *, environment: str):
        self._keys = parse_keyring(keyring, active_key_id, environment)
        self._active = active_key_id
        self._environment = environment

    def _aad(self, *, key_id, user_id, connection_id, purpose, provider) -> bytes:
        if (
            not isinstance(user_id, UUID)
            or not isinstance(connection_id, UUID)
            or not isinstance(purpose, str)
            or purpose not in {"access_token", "refresh_token"}
            or not isinstance(provider, str)
            or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", provider)
        ):
            raise TokenCryptoError("invalid_context")
        return json.dumps(
            {
                "domain": "kairoid:provider-token",
                "version": 1,
                "key_id": key_id,
                "environment": self._environment,
                "provider": provider,
                "user_id": str(user_id),
                "connection_id": str(connection_id),
                "purpose": purpose,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")

    def encrypt_secret(self, plaintext: SecretStr, **context) -> dict:
        if not isinstance(plaintext, SecretStr):
            raise TokenCryptoError("invalid_plaintext")
        try:
            value = plaintext.get_secret_value().encode("utf-8")
        except UnicodeError:
            raise TokenCryptoError("invalid_plaintext") from None
        if not value or len(value) > MAX_TOKEN_BYTES or not value.strip():
            raise TokenCryptoError("invalid_plaintext")
        nonce = secrets.token_bytes(12)
        aad = self._aad(key_id=self._active, **context)
        ciphertext = AESGCM(self._keys[self._active]).encrypt(nonce, value, aad)
        return {
            "version": 1,
            "key_id": self._active,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }

    def decrypt_secret(self, envelope: object, **context) -> SecretStr:
        if not isinstance(envelope, dict) or set(envelope) != {
            "version",
            "key_id",
            "nonce",
            "ciphertext",
        }:
            raise TokenCryptoError("malformed_envelope")
        if type(envelope["version"]) is not int or envelope["version"] != 1:
            raise TokenCryptoError("unknown_version")
        key_id = envelope["key_id"]
        if not isinstance(key_id, str) or key_id not in self._keys:
            raise TokenCryptoError("unknown_key_id")
        try:
            nonce = _decode(envelope["nonce"], limit=16)
            ciphertext = _decode(envelope["ciphertext"], limit=22_000)
            if len(nonce) != 12 or not 16 < len(ciphertext) <= MAX_TOKEN_BYTES + 16:
                raise ValueError()
        except (ValueError, TypeError, binascii.Error):
            raise TokenCryptoError("malformed_envelope") from None
        aad = self._aad(key_id=key_id, **context)
        try:
            value = AESGCM(self._keys[key_id]).decrypt(nonce, ciphertext, aad).decode("utf-8")
            if not value.strip():
                raise ValueError()
        except (InvalidTag, ValueError):
            raise TokenCryptoError("authentication_failed") from None
        return SecretStr(value)
