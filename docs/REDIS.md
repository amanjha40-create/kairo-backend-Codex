# Redis integration

The API uses **`redis.asyncio`** with a single shared connection pool per process (`app/infrastructure/redis/client.py`).

## Configuration

| Variable | Purpose |
|----------|---------|
| `REDIS_URL` | Connection URL (default `redis://localhost:6379/0`). |
| `REDIS_MAX_CONNECTIONS` | Pool size cap (default `50`). |
| `REDIS_SOCKET_CONNECT_TIMEOUT` | Connect timeout in seconds (default `5`). |
| `REDIS_SOCKET_TIMEOUT` | Read/write timeout in seconds (default `5`). |
| `REDIS_HEALTH_CHECK_INTERVAL` | Pool connection health check interval in seconds (default `30`). |
| `REDIS_KEY_PREFIX` | Optional namespace prefix for keys; empty uses `APP_NAME:APP_ENV`. |
| `REDIS_REQUIRED_FOR_READY` | If `true`, `/api/v1/health/ready` returns **503** when Redis is down (default `false`). |

## Usage in FastAPI

Inject the client:

```python
from fastapi import Depends
from redis.asyncio import Redis

from app.infrastructure.redis import get_redis

@router.get("/example")
async def example(redis: Redis = Depends(get_redis)):
    await redis.set("k", "v", ex=60)
```

## Keys and cache

- **`build_key_prefix()`** / **`RedisKeys`** — consistent namespacing (`rate_limit`, `otp`, `cache`, `session_blocklist`).
- **`get_json` / `set_json` / `delete_key`** — JSON helpers with optional TTL (`app/infrastructure/redis/cache.py`).

## Lifecycle

The pool is created lazily on first use and closed in **`app/main.py`** shutdown via **`close_redis_client()`** after the database engine is disposed.

## Readiness

`/api/v1/health/ready` always probes Redis when possible and includes **`redis`: `reachable` \| `unreachable`** in the JSON body. Fail-open unless **`REDIS_REQUIRED_FOR_READY=true`**.
