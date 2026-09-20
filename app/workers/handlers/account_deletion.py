"""Queue acceleration; the DB sweeper remains authoritative."""

from uuid import UUID

from redis.asyncio import Redis

from app.config import get_settings
from app.db.session import async_session_factory
from app.services.account_deletion_purge import sweep_deletions
from app.workers.registry import register_handler


@register_handler("account.deletion.purge")
async def purge_account(data, session):
    settings = get_settings()
    try:
        deletion_id = UUID(str(data["deletion_id"]))
        async with async_session_factory() as purge_session:
            async with Redis.from_url(settings.redis_url) as redis:
                await sweep_deletions(purge_session, settings, redis, deletion_id=deletion_id)
    except Exception:
        raise RuntimeError("account_deletion_worker_failed") from None
