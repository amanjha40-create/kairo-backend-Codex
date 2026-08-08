"""Pre-composed permission guards for the verification review console."""

from __future__ import annotations

from app.auth.deps import CurrentUser, require_permission, require_roles
from app.core.constants import VERIFICATION_REVIEW_ROLES
from app.core.permissions import Permission

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

# Role assignment — superadmin only
require_role_manager = require_permission(Permission.ASSIGN_ROLES)

# ---------------------------------------------------------------------------
# Legacy alias — kept so existing imports don't break during migration.
# New code should use the named guards above.
# ---------------------------------------------------------------------------
require_verification_staff = require_roles(*VERIFICATION_REVIEW_ROLES)

__all__ = [
    "CurrentUser",
    "require_assign",
    "require_dispatch",
    "require_finalizer",
    "require_remark",
    "require_request_more_info",
    "require_reviewer",
    "require_priority",
    "require_role_manager",
    "require_user_manager",
    "require_verification_staff",  # legacy
    "require_view_cases",
]
