"""Internship service — create, list, update, delete."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.internship import Internship
from app.repositories.internship import InternshipRepository
from app.schemas.internship import InternshipCreateRequest, InternshipUpdateRequest


class InternshipService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = InternshipRepository(session)

    async def create(self, user_id: UUID, payload: InternshipCreateRequest) -> Internship:
        item = Internship(
            user_id=user_id,
            company_name=payload.company_name,
            role=payload.role,
            description=payload.description,
            start_date=payload.start_date,
            end_date=payload.end_date,
            is_ongoing=payload.is_ongoing,
            is_paid=payload.is_paid,
            stipend_amount=payload.stipend_amount,
            stipend_currency=payload.stipend_currency,
        )
        await self._repo.create(item)
        await self._session.commit()
        await self._session.refresh(item)
        return item

    async def list_for_user(self, user_id: UUID, *, offset: int = 0, limit: int = 50):
        return await self._repo.list_for_user(user_id, offset=offset, limit=limit)

    async def get_owned(self, user_id: UUID, item_id: UUID) -> Internship:
        item = await self._repo.get_owned(item_id, user_id)
        if item is None:
            raise NotFoundError("Internship not found")
        return item

    async def update(
        self, user_id: UUID, item_id: UUID, payload: InternshipUpdateRequest,
    ) -> Internship:
        item = await self.get_owned(user_id, item_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(item, field, value)
        await self._session.commit()
        await self._session.refresh(item)
        return item

    async def delete(self, user_id: UUID, item_id: UUID) -> None:
        item = await self.get_owned(user_id, item_id)
        await self._repo.soft_delete(item)
        await self._session.commit()
