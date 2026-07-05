"""Redis package — async client, keys, cache helpers, FastAPI deps."""

from app.infrastructure.redis.cache import delete_key, get_json, set_json
from app.infrastructure.redis.client import close_redis_client, get_redis_client, ping_redis
from app.infrastructure.redis.deps import get_redis
from app.infrastructure.redis.keys import RedisKeys, build_key_prefix

__all__ = [
    "RedisKeys",
    "build_key_prefix",
    "close_redis_client",
    "delete_key",
    "get_json",
    "get_redis",
    "get_redis_client",
    "ping_redis",
    "set_json",
]
