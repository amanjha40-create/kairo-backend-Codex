"""FastAPI authentication dependencies — bearer JWT and RBAC guards."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import decode_token_safe
from app.config import Settings, get_settings
from app.core.constants import ACCESS_TOKEN_TYPE
from app.core.permissions import Permission, has_permission
from app.db.session import get_session
from app.exceptions import ForbiddenError, UnauthorizedError
from app.logging.context import bind_user_context
from app.repositories import UserRepository

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """Authenticated principal extracted from validated JWT + database."""

    id: UUID
    email: str
    role: str


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    """Reject missing/invalid tokens without leaking credential validity details."""

    if credentials is None:
        raise UnauthorizedError("Not authenticated")

    payload = decode_token_safe(settings, credentials.credentials)
    if payload is None:
        raise UnauthorizedError("Invalid or expired token")

    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise UnauthorizedError("Invalid token type")

    try:
        uid = UUID(str(payload["sub"]))
    except (KeyError, ValueError, TypeError):
        raise UnauthorizedError("Invalid token")

    repo = UserRepository(session)
    user = await repo.get_by_id(uid)
    if user is None or not user.is_active or user.email_verified_at is None:
        raise UnauthorizedError("User not found or inactive")

    bind_user_context(str(user.id))
    return CurrentUser(id=user.id, email=user.email, role=user.role)


async def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> CurrentUser | None:
    """Return the current user if a valid bearer token is present, else None."""
    if credentials is None:
        return None
    payload = decode_token_safe(settings, credentials.credentials)
    if payload is None or payload.get("type") != ACCESS_TOKEN_TYPE:
        return None
    try:
        uid = UUID(str(payload["sub"]))
    except (KeyError, ValueError, TypeError):
        return None
    repo = UserRepository(session)
    user = await repo.get_by_id(uid)
    if user is None or not user.is_active or user.email_verified_at is None:
        return None
    return CurrentUser(id=user.id, email=user.email, role=user.role)


def require_roles(*roles: str):
    """RBAC dependency factory — guards by exact role membership.

    Prefer ``require_permission()`` for new routes; this remains for
    legacy callers and special-purpose role-exact checks.
    """

    allowed = set(roles)

    async def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise ForbiddenError("Insufficient permissions")
        return user

    return checker


def require_permission(permission: Permission):
    """Permission-based RBAC dependency factory.

    Preferred over ``require_roles()`` for all new routes — decouples
    the route from specific role names so new roles can be granted the
    permission without changing route code.

    Usage::

        @router.post("/admin/verifications/{id}/approve")
        async def approve(
            reviewer: Annotated[CurrentUser, Depends(require_permission(Permission.REVIEW_VERIFICATION))],
        ): ...
    """

    async def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not has_permission(user.role, permission):
            raise ForbiddenError("Insufficient permissions")
        return user

    # Give the inner function a unique name so FastAPI's dependency cache
    # treats different permission values as distinct dependencies.
    checker.__name__ = f"require_{permission.value}"
    return checker
