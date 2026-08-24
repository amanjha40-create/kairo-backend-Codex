"""Async engine, session factory, and request-scoped session dependency."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.config.settings import AppEnvironment
from app.db.base import Base
from app.db.url import build_async_database_config

settings = get_settings()

_echo_sql = (
    settings.database_echo_sql
    if settings.database_echo_sql is not None
    else (settings.app_env == AppEnvironment.DEVELOPMENT)
)

_async_database_url, _async_connect_args = build_async_database_config(
    settings.runtime_database_url
)

_engine_kwargs = {
    "connect_args": _async_connect_args,
    "pool_pre_ping": True,
    "echo": _echo_sql,
}
if settings.app_env == AppEnvironment.TEST:
    # Function-scoped asyncio test loops cannot safely share pooled asyncpg connections.
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs["pool_size"] = settings.database_pool_size
    _engine_kwargs["max_overflow"] = settings.database_max_overflow
    _engine_kwargs["pool_timeout"] = settings.database_pool_timeout

engine: AsyncEngine = create_async_engine(_async_database_url, **_engine_kwargs)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield one session per request — services own `commit`; rollback on uncaught errors."""

    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Dispose connection pool — call on application shutdown."""

    await engine.dispose()


async def init_db_schema() -> None:
    """Development helper — create tables from metadata. Production uses Alembic."""

    import app.models  # noqa: F401 — register models

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
