"""Import handler modules so **`@register_handler`** runs at startup."""

from __future__ import annotations

from app.workers.handlers import builtin  # noqa: F401
from app.workers.handlers import email  # noqa: F401
from app.workers.handlers import extraction  # noqa: F401
from app.workers.handlers import resume  # noqa: F401
