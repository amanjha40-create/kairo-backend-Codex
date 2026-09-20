"""Serialize private file/share issuance with the authoritative deletion transaction."""

from sqlalchemy import select

from app.exceptions import NotFoundError
from app.models.user import User


async def lock_private_owner(session, user_id):
    user = (
        await session.execute(
            select(User)
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if user is None or user.deleted_at is not None or not user.is_active:
        raise NotFoundError("Account unavailable")
    return user
