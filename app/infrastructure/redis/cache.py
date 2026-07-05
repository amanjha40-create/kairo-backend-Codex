"""High-level cache helpers — JSON payloads with TTL."""

from __future__ import annotations

import json
from typing import Any, TypeVar

from redis.asyncio import Redis

T = TypeVar("T")


async def get_json(client: Redis, key: str) -> Any | None:
    """Fetch and parse JSON — returns ``None`` on cache miss."""

    raw = await client.get(key)
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


async def set_json(
    client: Redis,
    key: str,
    value: Any,
    *,
    ttl_seconds: int | None = None,
) -> None:
    """Serialize JSON and optionally set **EX** TTL."""

    payload = json.dumps(value, default=str)
    if ttl_seconds is not None:
        await client.set(key, payload, ex=ttl_seconds)
    else:
        await client.set(key, payload)


async def delete_key(client: Redis, key: str) -> None:
    await client.delete(key)
