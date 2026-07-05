"""Cryptographic primitives — re-exported from **`app.auth`** for backward compatibility."""

from __future__ import annotations

from app.auth.passwords import hash_password, verify_password
from app.auth.tokens import (
    create_access_token,
    decode_token,
    decode_token_safe,
    generate_opaque_refresh_raw,
    hash_refresh_token,
)

__all__ = [
    "create_access_token",
    "decode_token",
    "decode_token_safe",
    "generate_opaque_refresh_raw",
    "hash_password",
    "hash_refresh_token",
    "verify_password",
]
