"""Password hashing and verification (Argon2id; legacy bcrypt for migration)."""

from __future__ import annotations

import bcrypt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)

_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")


def hash_password(plain: str) -> str:
    """Hash password with Argon2id."""

    return _hasher.hash(plain)


def _verify_bcrypt(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def verify_password(plain: str, hashed: str) -> bool:
    """Verify plain password against Argon2id or legacy bcrypt hash."""

    if hashed.startswith("$argon2"):
        try:
            _hasher.verify(hashed, plain)
            return True
        except VerifyMismatchError:
            return False
        except InvalidHashError:
            return False
    if hashed.startswith(_BCRYPT_PREFIXES):
        return _verify_bcrypt(plain, hashed)
    return False


def password_needs_rehash(hashed: str) -> bool:
    """True when stored hash should be upgraded to current Argon2 parameters."""

    if not hashed.startswith("$argon2"):
        return True
    try:
        return _hasher.check_needs_rehash(hashed)
    except InvalidHashError:
        return True
