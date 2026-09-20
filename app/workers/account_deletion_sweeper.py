"""Independent durable sweeper: python -m app.workers.account_deletion_sweeper.

Read-only aggregate status by default. --execute enables one bounded sweep;
schedule periodically in the approved environment during a separately approved rollout.
"""

import argparse
import asyncio
import json

from redis.asyncio import Redis
from sqlalchemy import func, select

from app.config import get_settings
from app.db.session import async_session_factory
from app.models.account_deletion import AccountDeletion
from app.services.account_deletion_purge import sweep_deletions


async def main(execute=False):
    settings = get_settings()
    async with async_session_factory() as session:
        if not execute:
            rows = (
                await session.execute(
                    select(AccountDeletion.status, func.count()).group_by(AccountDeletion.status)
                )
            ).all()
            print(json.dumps(dict(rows)))
            return
        async with Redis.from_url(settings.redis_url) as redis:
            result = await sweep_deletions(session, settings, redis)
            print(json.dumps(result or {"due_requests": 0}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(main(args.execute))
    except Exception:
        # No raw DB/SDK traceback, which can contain object references or parameters.
        raise SystemExit(
            "account_deletion_sweep_failed; inspect sanitized operational status"
        ) from None
