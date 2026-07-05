"""FastAPI dependency for Redis — yields shared async client."""

from __future__ import annotations

from redis.asyncio import Redis

from app.infrastructure.redis.client import get_redis_client


async def get_redis() -> Redis:
    """Inject **`Redis`** into routes or services (singleton pool per process)."""

    return await get_redis_client()
