"""Register async handlers keyed by envelope **`type`**."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

HandlerFn = Callable[[dict[str, Any], AsyncSession], Awaitable[None]]

_HANDLERS: dict[str, HandlerFn] = {}


def register_handler(message_type: str) -> Callable[[HandlerFn], HandlerFn]:
    """Decorator — **`async def fn(data, session)`** (session is positional second arg)."""

    def decorator(fn: HandlerFn) -> HandlerFn:
        _HANDLERS[message_type] = fn
        return fn

    return decorator


def get_handler(message_type: str) -> HandlerFn | None:
    return _HANDLERS.get(message_type)


def registered_types() -> frozenset[str]:
    return frozenset(_HANDLERS.keys())
