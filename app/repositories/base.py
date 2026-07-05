"""Generic async repository — reusable CRUD and pagination primitives."""

from __future__ import annotations

from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Abstract data access for a single SQLAlchemy model."""

    def __init__(self, session: AsyncSession, model: type[ModelT]) -> None:
        self._session = session
        self._model = model

    async def get_by_id(self, obj_id: UUID) -> ModelT | None:
        stmt = select(self._model).where(self._model.id == obj_id)  # type: ignore[attr-defined]
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def count(self, *filters: ColumnElement[bool]) -> int:
        stmt = select(func.count()).select_from(self._model)
        for f in filters:
            stmt = stmt.where(f)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def list_page(
        self,
        *,
        offset: int,
        limit: int,
        base_filters: list[ColumnElement[bool]] | None = None,
        order_by: Any = None,
    ) -> tuple[list[ModelT], int]:
        filters = base_filters or []
        count_stmt = select(func.count()).select_from(self._model)
        for f in filters:
            count_stmt = count_stmt.where(f)
        total = int((await self._session.execute(count_stmt)).scalar_one())

        stmt: Select[tuple[ModelT]] = select(self._model)
        for f in filters:
            stmt = stmt.where(f)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        stmt = stmt.offset(offset).limit(limit)
        rows = await self._session.execute(stmt)
        items = list(rows.scalars().all())
        return items, total
