"""Password hashing unit tests."""

from __future__ import annotations

import bcrypt

from app.auth.passwords import hash_password, password_needs_rehash, verify_password


def test_hash_and_verify_argon2() -> None:
    hashed = hash_password("secure-password-12")
    assert hashed.startswith("$argon2")
    assert verify_password("secure-password-12", hashed)
    assert not verify_password("wrong-password", hashed)
    assert not password_needs_rehash(hashed)


def test_verify_legacy_bcrypt_and_needs_rehash() -> None:
    legacy = bcrypt.hashpw(b"legacy-password", bcrypt.gensalt()).decode("utf-8")
    assert verify_password("legacy-password", legacy)
    assert password_needs_rehash(legacy)
