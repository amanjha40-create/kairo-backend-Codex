"""Async engine, session factory, and request-scoped session dependency."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.config.settings import AppEnvironment
from app.db.base import Base

settings = get_settings()

_echo_sql = (
    settings.database_echo_sql
    if settings.database_echo_sql is not None
    else (settings.app_env == AppEnvironment.DEVELOPMENT)
)

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_timeout=settings.database_pool_timeout,
    echo=_echo_sql,
)

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
