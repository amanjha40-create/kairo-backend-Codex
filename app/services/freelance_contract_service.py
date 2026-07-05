"""Freelance contract service — create, list, update, delete."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.freelance_contract import FreelanceContract
from app.repositories.freelance_contract import FreelanceContractRepository
from app.schemas.freelance_contract import FreelanceContractCreateRequest, FreelanceContractUpdateRequest


class FreelanceContractService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = FreelanceContractRepository(session)

    async def create(self, user_id: UUID, payload: FreelanceContractCreateRequest) -> FreelanceContract:
        item = FreelanceContract(
            user_id=user_id,
            client_name=payload.client_name,
            project_title=payload.project_title,
            description=payload.description,
            start_date=payload.start_date,
            end_date=payload.end_date,
            is_ongoing=payload.is_ongoing,
        )
        await self._repo.create(item)
        await self._session.commit()
        await self._session.refresh(item)
        return item

    async def list_for_user(self, user_id: UUID, *, offset: int = 0, limit: int = 50):
        return await self._repo.list_for_user(user_id, offset=offset, limit=limit)

    async def get_owned(self, user_id: UUID, item_id: UUID) -> FreelanceContract:
        item = await self._repo.get_owned(item_id, user_id)
        if item is None:
            raise NotFoundError("Freelance contract not found")
        return item

    async def update(
        self, user_id: UUID, item_id: UUID, payload: FreelanceContractUpdateRequest,
    ) -> FreelanceContract:
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
