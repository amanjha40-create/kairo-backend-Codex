"""Admin Portal authentication/session boundary."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.deps import CurrentUser, require_permission
from app.core.permissions import ROLE_PERMISSIONS, Permission
from app.schemas.admin_session import AdminSessionAccount, AdminSessionResponse

router = APIRouter(prefix="/admin", tags=["admin-auth"])


def _initials(name: str | None, email: str) -> str:
    """Build a stable, non-sensitive avatar fallback from the account identity."""

    words = [part for part in (name or "").split() if part]
    if len(words) >= 2:
        return (words[0][0] + words[-1][0]).upper()
    if words:
        return words[0][:2].upper()
    return email[:2].upper()


@router.get(
    "/session",
    response_model=AdminSessionResponse,
    summary="Read the authenticated Admin Portal session",
)
async def read_admin_session(
    current: CurrentUser = Depends(require_permission(Permission.ACCESS_ADMIN_PORTAL)),  # noqa: B008
) -> AdminSessionResponse:
    permissions = sorted(
        permission.value for permission in ROLE_PERMISSIONS.get(current.role, frozenset())
    )
    return AdminSessionResponse(
        account=AdminSessionAccount(
            id=current.id,
            email=current.email,
            name=current.full_name,
            initials=_initials(current.full_name, current.email),
            role_key=current.role,
            permissions=permissions,
            is_active=current.is_active,
        )
    )
