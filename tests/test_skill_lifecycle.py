from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services import skill_lifecycle


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []
        self.flush = AsyncMock()

    async def scalars(self, statement):
        self.statements.append(statement)
        return _Rows(self.rows)


@pytest.mark.asyncio
async def test_deleted_skill_releases_name_without_reactivating_history(monkeypatch) -> None:
    user_id = uuid4()
    deleted = SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        normalized_name="financial modelling",
        deleted_at=datetime.now(UTC),
    )
    session = _Session([deleted])
    owner_lock = AsyncMock()
    monkeypatch.setattr(skill_lifecycle, "lock_private_owner", owner_lock)

    name, normalized, active = await skill_lifecycle.reserve_skill_name(
        session, user_id, "  Financial   Modelling "
    )

    assert (name, normalized, active) == (
        "Financial Modelling",
        "financial modelling",
        None,
    )
    assert deleted.deleted_at is not None
    assert deleted.normalized_name == skill_lifecycle.deleted_skill_key(deleted.id)
    owner_lock.assert_awaited_once_with(session, user_id)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_active_skill_remains_canonical_duplicate(monkeypatch) -> None:
    user_id = uuid4()
    active = SimpleNamespace(
        id=uuid4(), user_id=user_id, normalized_name="python", deleted_at=None
    )
    session = _Session([active])
    monkeypatch.setattr(skill_lifecycle, "lock_private_owner", AsyncMock())

    _, _, existing = await skill_lifecycle.reserve_skill_name(session, user_id, "Python")

    assert existing is active
    assert active.normalized_name == "python"


@pytest.mark.asyncio
async def test_skill_name_reservation_is_owner_scoped_and_lock_first(monkeypatch) -> None:
    events = []
    user_id = uuid4()
    session = _Session([])

    async def owner_lock(_session, locked_user_id):
        events.append(("lock", locked_user_id))

    original_scalars = session.scalars

    async def scalars(statement):
        events.append(("query", None))
        return await original_scalars(statement)

    session.scalars = scalars
    monkeypatch.setattr(skill_lifecycle, "lock_private_owner", owner_lock)

    await skill_lifecycle.reserve_skill_name(session, user_id, "SQL")

    assert events == [("lock", user_id), ("query", None)]
    statement = str(session.statements[0])
    assert "skills.user_id" in statement
    assert "skills.normalized_name" in statement
    assert "FOR UPDATE" in statement


@pytest.mark.asyncio
async def test_soft_delete_tombstones_key_and_preserves_row(monkeypatch) -> None:
    user_id = uuid4()
    row = SimpleNamespace(
        id=uuid4(), user_id=user_id, normalized_name="python", deleted_at=None
    )
    session = SimpleNamespace(scalar=AsyncMock(return_value=row), flush=AsyncMock())
    monkeypatch.setattr(skill_lifecycle, "lock_private_owner", AsyncMock())

    result = await skill_lifecycle.soft_delete_skill(session, user_id, row.id)

    assert result is row
    assert row.deleted_at is not None
    assert row.normalized_name == skill_lifecycle.deleted_skill_key(row.id)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_legacy_deleted_collision_retry_is_idempotent(monkeypatch) -> None:
    user_id = uuid4()
    deleted = SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        normalized_name="python",
        deleted_at=datetime.now(UTC),
    )
    session = _Session([deleted])
    monkeypatch.setattr(skill_lifecycle, "lock_private_owner", AsyncMock())

    await skill_lifecycle.reserve_skill_name(session, user_id, "Python")
    session.rows = []
    _, normalized, active = await skill_lifecycle.reserve_skill_name(
        session, user_id, "Python"
    )

    assert normalized == "python"
    assert active is None
    assert deleted.normalized_name == skill_lifecycle.deleted_skill_key(deleted.id)
