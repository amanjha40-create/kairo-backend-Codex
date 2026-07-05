"""FastAPI dependency aliases for database sessions."""

from __future__ import annotations

from app.db.session import get_session

# Common FastAPI naming convention
get_db = get_session

__all__ = ["get_db", "get_session"]
