"""Pre-composed permission guards for the verification review console."""

from __future__ import annotations

from app.auth.deps import CurrentUser, require_permission, require_roles
from app.core.constants import VERIFICATION_REVIEW_ROLES
from app.core.permissions import Permission

# Any authenticated internal operator allowed into the Admin portal.
require_admin_portal = require_permission(Permission.ACCESS_ADMIN_PORTAL)

# View-only access — support, moderator, hr, admin, superadmin
require_view_cases = require_permission(Permission.VIEW_ALL_CASES)

# Remark only — moderator, hr, admin, superadmin
require_remark = require_permission(Permission.ADD_REMARK)

# Assign reviewer — admin, superadmin
require_assign = require_permission(Permission.ASSIGN_REVIEWER)

# Priority changes — admin, superadmin
require_priority = require_permission(Permission.CHANGE_VERIFICATION_PRIORITY)

# Legacy non-final review operations — hr, admin, superadmin
require_reviewer = require_permission(Permission.REVIEW_VERIFICATION)

# Pre-dispatch actions — admin, superadmin
require_dispatch = require_permission(Permission.DISPATCH_VERIFICATION)

# Final Career-state actions — admin, superadmin
require_finalizer = require_permission(Permission.FINALIZE_VERIFICATION)

# Legacy correction guard retained for compatibility.
require_request_more_info = require_permission(Permission.REQUEST_MORE_INFO)

# User management — admin, superadmin
require_user_manager = require_permission(Permission.MANAGE_USERS)
require_user_reader = require_permission(Permission.READ_USERS)
require_user_account_manager = require_permission(Permission.MANAGE_USER_ACCOUNTS)
require_user_security_manager = require_permission(Permission.MANAGE_USER_SECURITY)
require_user_note_manager = require_permission(Permission.MANAGE_USER_NOTES)
require_trust_safety_read = require_permission(Permission.TRUST_SAFETY_READ)
require_trust_safety_create = require_permission(Permission.TRUST_SAFETY_CREATE)
require_trust_safety_assign = require_permission(Permission.TRUST_SAFETY_ASSIGN)
require_trust_safety_note = require_permission(Permission.TRUST_SAFETY_NOTE)
require_trust_safety_update_severity = require_permission(
    Permission.TRUST_SAFETY_UPDATE_SEVERITY
)
require_trust_safety_resolve = require_permission(Permission.TRUST_SAFETY_RESOLVE)

# Role assignment — superadmin only
require_role_manager = require_permission(Permission.ASSIGN_ROLES)

# ---------------------------------------------------------------------------
# Legacy alias — kept so existing imports don't break during migration.
# New code should use the named guards above.
# ---------------------------------------------------------------------------
require_verification_staff = require_roles(*VERIFICATION_REVIEW_ROLES)

__all__ = [
    "CurrentUser",
    "require_admin_portal",
    "require_assign",
    "require_dispatch",
    "require_finalizer",
    "require_remark",
    "require_request_more_info",
    "require_reviewer",
    "require_priority",
    "require_user_account_manager",
    "require_user_note_manager",
    "require_user_reader",
    "require_user_security_manager",
    "require_trust_safety_assign",
    "require_trust_safety_create",
    "require_trust_safety_note",
    "require_trust_safety_read",
    "require_trust_safety_resolve",
    "require_trust_safety_update_severity",
    "require_role_manager",
    "require_user_manager",
    "require_verification_staff",  # legacy
    "require_view_cases",
]
