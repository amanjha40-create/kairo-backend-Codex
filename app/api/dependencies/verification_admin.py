"""Pre-composed permission guards for the verification review console.

Import these in admin route files instead of building guards inline.
Each name maps to the minimum permission a caller needs for that class
of action — so moderators, hr, admin, and superadmin each land on the
right guard automatically via ``ROLE_PERMISSIONS``.
"""

from __future__ import annotations

from app.auth.deps import CurrentUser, require_permission
from app.core.constants import VERIFICATION_REVIEW_ROLES
from app.auth.deps import require_roles
from app.core.permissions import Permission

# View-only access — support, moderator, hr, admin, superadmin
require_view_cases = require_permission(Permission.VIEW_ALL_CASES)

# Remark only — moderator, hr, admin, superadmin
require_remark = require_permission(Permission.ADD_REMARK)

# Assign reviewer — admin, superadmin
require_assign = require_permission(Permission.ASSIGN_REVIEWER)

# Approve / reject — hr, admin, superadmin
require_reviewer = require_permission(Permission.REVIEW_VERIFICATION)

# Request subject corrections — hr, admin, superadmin
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
    "require_remark",
    "require_request_more_info",
    "require_reviewer",
    "require_role_manager",
    "require_user_manager",
    "require_verification_staff",  # legacy
    "require_view_cases",
]
