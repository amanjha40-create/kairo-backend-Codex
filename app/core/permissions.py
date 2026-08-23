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
        reviewer: Annotated[
            CurrentUser,
            Depends(require_permission(Permission.REVIEW_VERIFICATION)),
        ],
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
    ACCESS_ADMIN_PORTAL = "access_admin_portal"
    VIEW_ALL_CASES = "view_all_cases"
    VIEW_AUDIT_LOG = "view_audit_log"
    ADD_REMARK = "add_remark"
    ASSIGN_REVIEWER = "assign_reviewer"
    CHANGE_VERIFICATION_PRIORITY = "change_verification_priority"
    REVIEW_VERIFICATION = "review_verification"   # approve / reject
    REQUEST_MORE_INFO = "request_more_info"        # → additional_info_requested
    DISPATCH_VERIFICATION = "dispatch_verification"
    FINALIZE_VERIFICATION = "finalize_verification"

    # --- User-management operations ---
    READ_USERS = "read_users"
    MANAGE_USER_ACCOUNTS = "manage_user_accounts"
    MANAGE_USER_SECURITY = "manage_user_security"
    MANAGE_USER_NOTES = "manage_user_notes"
    MANAGE_USERS = "manage_users"    # create / update / deactivate users
    ASSIGN_ROLES = "assign_roles"    # change a user's role

    # --- Trust & Safety operations ---
    TRUST_SAFETY_READ = "trust_safety_read"
    TRUST_SAFETY_CREATE = "trust_safety_create"
    TRUST_SAFETY_ASSIGN = "trust_safety_assign"
    TRUST_SAFETY_NOTE = "trust_safety_note"
    TRUST_SAFETY_UPDATE_SEVERITY = "trust_safety_update_severity"
    TRUST_SAFETY_RESOLVE = "trust_safety_resolve"

    # --- System Operations ---
    SYSTEM_OPERATIONS_READ = "system_operations_read"
    SYSTEM_OPERATIONS_INCIDENT_CREATE = "system_operations_incident_create"
    SYSTEM_OPERATIONS_INCIDENT_UPDATE = "system_operations_incident_update"
    SYSTEM_OPERATIONS_RETRY = "system_operations_retry"

    # --- Admin settings & administration ---
    ADMIN_SETTINGS_READ = "admin_settings_read"
    ADMIN_SETTINGS_UPDATE_SELF = "admin_settings_update_self"
    ADMIN_ACCESS_READ = "admin_access_read"
    ADMIN_ACCESS_INVITE = "admin_access_invite"
    ADMIN_ACCESS_CHANGE_ROLE = "admin_access_change_role"
    ADMIN_ACCESS_DEACTIVATE = "admin_access_deactivate"
    ADMIN_ACCESS_RESTORE = "admin_access_restore"
    ADMIN_ACCESS_AUDIT_READ = "admin_access_audit_read"


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
        Permission.ACCESS_ADMIN_PORTAL,
        Permission.VIEW_ALL_CASES,
        Permission.VIEW_AUDIT_LOG,
        Permission.SYSTEM_OPERATIONS_READ,
        Permission.ADMIN_SETTINGS_READ,
        Permission.ADMIN_SETTINGS_UPDATE_SELF,
    }
)

_MODERATOR: frozenset[Permission] = frozenset(
    {
        Permission.ACCESS_ADMIN_PORTAL,
        Permission.VIEW_ALL_CASES,
        Permission.VIEW_AUDIT_LOG,
        Permission.ADD_REMARK,
        Permission.TRUST_SAFETY_READ,
        Permission.TRUST_SAFETY_NOTE,
        Permission.SYSTEM_OPERATIONS_READ,
        Permission.ADMIN_SETTINGS_READ,
        Permission.ADMIN_SETTINGS_UPDATE_SELF,
    }
)

_HR: frozenset[Permission] = frozenset(
    {
        Permission.ACCESS_ADMIN_PORTAL,
        Permission.VIEW_ALL_CASES,
        Permission.VIEW_AUDIT_LOG,
        Permission.ADD_REMARK,
        Permission.REVIEW_VERIFICATION,
        Permission.REQUEST_MORE_INFO,
        Permission.SYSTEM_OPERATIONS_READ,
        Permission.ADMIN_SETTINGS_READ,
        Permission.ADMIN_SETTINGS_UPDATE_SELF,
    }
)

_ADMIN: frozenset[Permission] = frozenset(
    {
        Permission.ACCESS_ADMIN_PORTAL,
        Permission.VIEW_ALL_CASES,
        Permission.VIEW_AUDIT_LOG,
        Permission.ADD_REMARK,
        Permission.ASSIGN_REVIEWER,
        Permission.CHANGE_VERIFICATION_PRIORITY,
        Permission.REVIEW_VERIFICATION,
        Permission.REQUEST_MORE_INFO,
        Permission.DISPATCH_VERIFICATION,
        Permission.FINALIZE_VERIFICATION,
        Permission.READ_USERS,
        Permission.MANAGE_USER_ACCOUNTS,
        Permission.MANAGE_USER_SECURITY,
        Permission.MANAGE_USER_NOTES,
        Permission.MANAGE_USERS,
        Permission.TRUST_SAFETY_READ,
        Permission.TRUST_SAFETY_CREATE,
        Permission.TRUST_SAFETY_ASSIGN,
        Permission.TRUST_SAFETY_NOTE,
        Permission.TRUST_SAFETY_UPDATE_SEVERITY,
        Permission.TRUST_SAFETY_RESOLVE,
        Permission.SYSTEM_OPERATIONS_READ,
        Permission.SYSTEM_OPERATIONS_INCIDENT_CREATE,
        Permission.SYSTEM_OPERATIONS_INCIDENT_UPDATE,
        Permission.SYSTEM_OPERATIONS_RETRY,
        Permission.ADMIN_SETTINGS_READ,
        Permission.ADMIN_SETTINGS_UPDATE_SELF,
        Permission.ADMIN_ACCESS_READ,
        Permission.ADMIN_ACCESS_INVITE,
        Permission.ADMIN_ACCESS_CHANGE_ROLE,
        Permission.ADMIN_ACCESS_DEACTIVATE,
        Permission.ADMIN_ACCESS_RESTORE,
        Permission.ADMIN_ACCESS_AUDIT_READ,
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
