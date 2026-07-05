"""Redis async client factory, lifecycle, and connectivity probes."""

from __future__ import annotations

import logging

import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import get_settings

logger = logging.getLogger(__name__)

_client: Redis | None = None


async def get_redis_client() -> Redis:
    """Return shared **`Redis`** connection pool — lazy init for API and workers."""

    global _client
    if _client is None:
        settings = get_settings()
        _client = aioredis.from_url(
            str(settings.redis_url),
            encoding="utf-8",
            decode_responses=True,
            max_connections=settings.redis_max_connections,
            socket_connect_timeout=settings.redis_socket_connect_timeout,
            socket_timeout=settings.redis_socket_timeout,
            health_check_interval=settings.redis_health_check_interval,
        )
        logger.info("Redis client pool initialized")
    return _client


async def close_redis_client() -> None:
    """Close connection pool — invoke from application shutdown."""

    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
        logger.info("Redis client pool closed")


async def ping_redis() -> bool:
    """Return ``True`` if **PING** succeeds."""

    try:
        client = await get_redis_client()
        return bool(await client.ping())
    except RedisError as exc:
        logger.warning(
            "Redis ping failed",
            extra={"error_type": type(exc).__name__},
        )
        return False
