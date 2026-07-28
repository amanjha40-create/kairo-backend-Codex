"""Database URL transformations for the async runtime and Alembic."""

from __future__ import annotations

from sqlalchemy.engine import URL, make_url


def build_async_database_config(database_url: str) -> tuple[URL, dict[str, str]]:
    """Translate libpq's ``sslmode`` query option for asyncpg."""

    url = make_url(database_url)
    query = dict(url.query)
    sslmode = query.pop("sslmode", None)
    connect_args = {"ssl": sslmode} if sslmode else {}
    return url.set(query=query), connect_args


def build_sync_database_url(database_url: str) -> str:
    """Select psycopg for Alembic while preserving libpq query options."""

    return database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
