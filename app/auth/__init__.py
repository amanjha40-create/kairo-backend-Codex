"""Authentication — passwords, JWTs, auth service, and FastAPI dependencies."""

from app.auth.deps import CurrentUser, bearer_scheme, get_current_user, require_roles
from app.auth.passwords import hash_password, verify_password
from app.auth.service import AuthService
from app.auth.tokens import (
    create_access_token,
    decode_token,
    decode_token_safe,
    generate_opaque_refresh_raw,
    hash_refresh_token,
)
from app.core.constants import ACCESS_TOKEN_TYPE

__all__ = [
    "ACCESS_TOKEN_TYPE",
    "AuthService",
    "CurrentUser",
    "bearer_scheme",
    "create_access_token",
    "decode_token",
    "decode_token_safe",
    "generate_opaque_refresh_raw",
    "get_current_user",
    "hash_password",
    "hash_refresh_token",
    "require_roles",
    "verify_password",
]
