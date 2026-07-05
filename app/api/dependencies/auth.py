"""Backward compatibility — prefer **`from app.auth.deps import ...`**."""

from app.auth.deps import CurrentUser, bearer_scheme, get_current_user, get_optional_current_user, require_roles

__all__ = ["CurrentUser", "bearer_scheme", "get_current_user", "get_optional_current_user", "require_roles"]
