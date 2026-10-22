"""Queue acceleration; the DB sweeper remains authoritative."""

import math
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import async_session_factory
from app.models.account_deletion import AccountDeletion
from app.services.account_deletion_purge import sweep_deletions
from app.workers.defer import SQS_MAX_VISIBILITY_TIMEOUT_SECONDS, DeferMessage
from app.workers.registry import register_handler

_CONCURRENT_CLAIM_RETRY_SECONDS = 30


async def _defer_seconds(session: AsyncSession, deletion_id: UUID) -> int | None:
    request = await session.scalar(select(AccountDeletion).where(AccountDeletion.id == deletion_id))
    if request is None or request.status in {"complete", "operator_review"}:
        return None
    if request.status not in {"purge_pending", "purge_partial"}:
        return None
    remaining = math.ceil((request.next_attempt_at - datetime.now(UTC)).total_seconds())
    return min(
        max(remaining, _CONCURRENT_CLAIM_RETRY_SECONDS),
        SQS_MAX_VISIBILITY_TIMEOUT_SECONDS,
    )


@register_handler("account.deletion.purge")
async def purge_account(data, session):
    settings = get_settings()
    try:
        deletion_id = UUID(str(data["deletion_id"]))
        async with async_session_factory() as purge_session:
            async with Redis.from_url(settings.redis_url) as redis:
                result = await sweep_deletions(
                    purge_session,
                    settings,
                    redis,
                    deletion_id=deletion_id,
                )
                if result is None:
                    delay_seconds = await _defer_seconds(purge_session, deletion_id)
                    if delay_seconds is not None:
                        raise DeferMessage(delay_seconds)
    except DeferMessage:
        raise
    except Exception:
        raise RuntimeError("account_deletion_worker_failed") from None
