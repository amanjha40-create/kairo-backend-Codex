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

from app.config import Settings, get_settings
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

def engine_options(
    runtime_settings: Settings,
    *,
    connect_args: dict[str, object],
    echo_sql: bool,
) -> dict[str, object]:
    options: dict[str, object] = {
        "connect_args": connect_args,
        "pool_pre_ping": True,
        "echo": echo_sql,
    }
    if runtime_settings.app_env == AppEnvironment.TEST:
        # Function-scoped asyncio test loops cannot safely share pooled asyncpg connections.
        options["poolclass"] = NullPool
    else:
        options["pool_size"] = runtime_settings.database_pool_size
        options["max_overflow"] = runtime_settings.database_max_overflow
        options["pool_timeout"] = runtime_settings.database_pool_timeout
    return options


_engine_kwargs = engine_options(
    settings,
    connect_args=_async_connect_args,
    echo_sql=_echo_sql,
)

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
