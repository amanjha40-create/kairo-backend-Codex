"""Database layer — async SQLAlchemy engine, sessions, transactions, health."""

from app.db.base import NAMING_CONVENTION, Base

__all__ = [
    "NAMING_CONVENTION",
    "Base",
    "async_session_factory",
    "dispose_engine",
    "engine",
    "get_db",
    "get_session",
    "init_db_schema",
    "ping_database",
    "transaction",
]


def __getattr__(name: str):
    """Lazily expose DB helpers without importing the whole stack at package import time."""

    if name in {"get_db", "get_session"}:
        from app.db.deps import get_db, get_session

        return {"get_db": get_db, "get_session": get_session}[name]

    if name in {"async_session_factory", "dispose_engine", "engine", "init_db_schema"}:
        from app.db.session import async_session_factory, dispose_engine, engine, init_db_schema

        return {
            "async_session_factory": async_session_factory,
            "dispose_engine": dispose_engine,
            "engine": engine,
            "init_db_schema": init_db_schema,
        }[name]

    if name == "ping_database":
        from app.db.health import ping_database

        return ping_database

    if name == "transaction":
        from app.db.transactions import transaction

        return transaction

    raise AttributeError(f"module 'app.db' has no attribute {name!r}")
