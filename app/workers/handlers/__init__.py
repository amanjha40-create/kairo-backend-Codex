"""Import handler modules so **`@register_handler`** runs at startup."""

from __future__ import annotations

from app.workers.handlers import (
    account_deletion,  # noqa: F401
    builtin,  # noqa: F401
    email,  # noqa: F401
    extraction,  # noqa: F401
    resume,  # noqa: F401
)
