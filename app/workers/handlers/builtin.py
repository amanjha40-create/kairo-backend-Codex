"""Built-in example handlers — extend with domain modules."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.workers.registry import register_handler

logger = logging.getLogger(__name__)


@register_handler("noop")
async def handle_noop(data: dict[str, Any], session: AsyncSession) -> None:
    """No-op sample — replace with real jobs (email, webhooks, imports)."""

    _ = (data, session)
    logger.debug("noop handler executed")
