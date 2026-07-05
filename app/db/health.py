"""Database connectivity checks for readiness probes."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def ping_database(session: AsyncSession) -> None:
    """Raise if the database is unreachable — cheap round-trip."""

    await session.execute(text("SELECT 1"))
