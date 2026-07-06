"""Test harness configuration — set required env before application import."""

from __future__ import annotations

import os

import pytest

# Required for Settings() and SQLAlchemy engine import side effects
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
)
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-jwt-secret-key-32-chars-minimum!!",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("APP_ENV", "test")

from app.config import reload_settings  # noqa: E402

reload_settings()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: tests requiring external services (Postgres, Redis)",
    )
