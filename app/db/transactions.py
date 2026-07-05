"""Explicit transaction boundaries — optional alternative to manual `session.commit()`.

Typical stack usage today: repositories + services call `await session.commit()` after success.
Use `transaction()` when you want a single block that auto-commits / rolls back.

Do not nest `transaction()` with manual commits inside the same block without understanding
SQLAlchemy transaction semantics.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession


@asynccontextmanager
async def transaction(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """Commit on clean exit, rollback on exception."""

    async with session.begin():
        yield session
