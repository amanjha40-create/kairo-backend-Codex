"""Consistent owner-before-token lock order for issuance and security revocation."""

from sqlalchemy import select

from app.models import User


async def lock_token_owners(session, owner_ids, *, refresh: bool = False):
    # The token lookup is a subquery, not a token lock. Re-read tokens after this lock.
    result = await session.execute(
        select(User)
        .where(User.id.in_(owner_ids))
        .order_by(User.id)
        .with_for_update(of=User)
        .execution_options(populate_existing=refresh)
    )
    return result.scalars().all()
