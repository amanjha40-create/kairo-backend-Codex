"""Canonical bounded database pool profiles for ECS application processes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class DatabasePoolProfile:
    pool_size: int
    max_overflow: int
    pool_timeout_seconds: int

    def environment(self) -> dict[str, str]:
        return {
            "DATABASE_POOL_SIZE": str(self.pool_size),
            "DATABASE_MAX_OVERFLOW": str(self.max_overflow),
            "DATABASE_POOL_TIMEOUT": str(self.pool_timeout_seconds),
        }

    def connection_ceiling(self, *, process_count: int) -> int:
        if process_count < 1:
            raise ValueError("process_count must be at least one")
        return process_count * (self.pool_size + self.max_overflow)


API_DATABASE_POOL = DatabasePoolProfile(
    pool_size=4,
    max_overflow=2,
    pool_timeout_seconds=10,
)

WORKER_DATABASE_POOL = DatabasePoolProfile(
    pool_size=3,
    max_overflow=1,
    pool_timeout_seconds=10,
)

DATABASE_POOL_PROFILES = {
    "api": API_DATABASE_POOL,
    "worker": WORKER_DATABASE_POOL,
}


def database_pool_profile(runtime_kind: str) -> DatabasePoolProfile:
    try:
        return DATABASE_POOL_PROFILES[runtime_kind]
    except KeyError as exc:
        raise ValueError(f"unsupported runtime kind: {runtime_kind}") from exc


def with_database_pool(
    environment: Mapping[str, str],
    profile: DatabasePoolProfile,
) -> dict[str, str]:
    """Return an environment with the canonical profile explicitly applied."""
    return {**environment, **profile.environment()}
