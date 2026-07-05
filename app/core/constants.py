"""Application-wide constants — avoid magic strings in business logic."""

from enum import StrEnum


class Role(StrEnum):
    """RBAC roles stored as lowercase strings in DB (VARCHAR 32).

    Adding a new role here is step 1 of 2 — also add its permission set
    in ``app.core.permissions.ROLE_PERMISSIONS``.

    Ordered roughly from least to most privileged for readability:
    """

    USER = "user"           # Applicant — manages own cases
    SUPPORT = "support"     # Read-only view of all cases (customer support)
    MODERATOR = "moderator" # View all cases + add remarks; cannot approve/reject
    HR = "hr"               # Full reviewer — approve / reject / assign
    ADMIN = "admin"         # HR powers + user management
    SUPERADMIN = "superadmin"  # All permissions including role assignment


# ---------------------------------------------------------------------------
# Legacy alias — kept for backward compatibility.
# New code should use Permission-based guards instead of role tuple checks.
# ---------------------------------------------------------------------------
VERIFICATION_REVIEW_ROLES: tuple[str, ...] = (
    Role.HR.value,
    Role.ADMIN.value,
    Role.SUPERADMIN.value,
)


# JWT claim typing for access tokens (opaque refresh tokens are stored hashed in Postgres)
ACCESS_TOKEN_TYPE = "access"

# Signup OTP stored in Redis under purpose namespace
SIGNUP_OTP_PURPOSE = "signup"

# Pagination caps (DoS / memory guardrails)
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# Redis key prefixes (colon-separated namespaces)
REDIS_PREFIX_RATE_LIMIT = "rl"
REDIS_PREFIX_REFRESH_DENY = "refresh_revoked"  # optional hot-path blacklist


class HttpHeader:
    REQUEST_ID = "X-Request-ID"
    CORRELATION_ID = "X-Correlation-ID"
