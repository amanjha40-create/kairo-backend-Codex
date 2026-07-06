"""Named permissions and the role → permission mapping.

Design
------
Each ``Role`` maps to a **frozen set** of ``Permission`` values.  Route-level
guards declare *which permission* they require, not *which roles*.  This means:

* Adding a new role  → add one entry to ``ROLE_PERMISSIONS`` here.
* Adding a new guard → add one ``Permission`` value here + one entry per role that
  should have it.  No route files need to change.

Usage in routes::

    from app.core.permissions import Permission
    from app.auth.deps import require_permission

    @router.post("/admin/verifications/{id}/approve")
    async def approve(
        reviewer: Annotated[CurrentUser, Depends(require_permission(Permission.REVIEW_VERIFICATION))],
        ...
    ): ...
"""

from __future__ import annotations

from enum import StrEnum

from app.core.constants import Role


class Permission(StrEnum):
    """All named permissions in the system.

    Keep entries grouped by domain so the table in ``ROLE_PERMISSIONS`` stays
    readable.
    """

    # --- Applicant / own-case operations ---
    VIEW_OWN_CASES = "view_own_cases"
    SUBMIT_CASE = "submit_case"

    # --- Staff / console operations ---
    VIEW_ALL_CASES = "view_all_cases"
    VIEW_AUDIT_LOG = "view_audit_log"
    ADD_REMARK = "add_remark"
    ASSIGN_REVIEWER = "assign_reviewer"
    REVIEW_VERIFICATION = "review_verification"   # approve / reject
    REQUEST_MORE_INFO = "request_more_info"        # → additional_info_requested

    # --- User-management operations ---
    MANAGE_USERS = "manage_users"    # create / update / deactivate users
    ASSIGN_ROLES = "assign_roles"    # change a user's role


# ---------------------------------------------------------------------------
# Role → permission mapping
# ---------------------------------------------------------------------------
# To add a new role:
#   1. Add the value to ``Role`` in app/core/constants.py
#   2. Add a row here with the permissions that role should have.
#
# To add a new permission:
#   1. Add the value to ``Permission`` above.
#   2. Add it to every role row that should hold it.
# ---------------------------------------------------------------------------

_USER: frozenset[Permission] = frozenset(
    {
        Permission.VIEW_OWN_CASES,
        Permission.SUBMIT_CASE,
    }
)

_SUPPORT: frozenset[Permission] = frozenset(
    {
        Permission.VIEW_ALL_CASES,
        Permission.VIEW_AUDIT_LOG,
    }
)

_MODERATOR: frozenset[Permission] = frozenset(
    {
        Permission.VIEW_ALL_CASES,
        Permission.VIEW_AUDIT_LOG,
        Permission.ADD_REMARK,
    }
)

_HR: frozenset[Permission] = frozenset(
    {
        Permission.VIEW_ALL_CASES,
        Permission.VIEW_AUDIT_LOG,
        Permission.ADD_REMARK,
        Permission.REVIEW_VERIFICATION,
        Permission.REQUEST_MORE_INFO,
    }
)

_ADMIN: frozenset[Permission] = frozenset(
    {
        Permission.VIEW_ALL_CASES,
        Permission.VIEW_AUDIT_LOG,
        Permission.ADD_REMARK,
        Permission.ASSIGN_REVIEWER,
        Permission.REVIEW_VERIFICATION,
        Permission.REQUEST_MORE_INFO,
        Permission.MANAGE_USERS,
    }
)

_SUPERADMIN: frozenset[Permission] = frozenset(Permission)  # all permissions

ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    Role.USER: _USER,
    Role.SUPPORT: _SUPPORT,
    Role.MODERATOR: _MODERATOR,
    Role.HR: _HR,
    Role.ADMIN: _ADMIN,
    Role.SUPERADMIN: _SUPERADMIN,
}


def has_permission(role: str, permission: Permission) -> bool:
    """Return ``True`` if *role* includes *permission*.

    Unknown roles (e.g. legacy values not yet in ``ROLE_PERMISSIONS``) are
    treated as having **no** permissions — fail-safe default.
    """
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def get_roles_with_permission(permission: Permission) -> frozenset[str]:
    """Return the set of role names that hold *permission*.

    Useful for building role-aware UI menus or admin tooling without
    hard-coding role lists.
    """
    return frozenset(role for role, perms in ROLE_PERMISSIONS.items() if permission in perms)
