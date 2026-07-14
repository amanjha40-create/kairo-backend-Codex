"""Employer verification request persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import EmployerVerificationRequest, Employment
from app.repositories.base import BaseRepository


class EmployerVerificationRepository(BaseRepository[EmployerVerificationRequest]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, EmployerVerificationRequest)

    async def create(self, entity: EmployerVerificationRequest) -> EmployerVerificationRequest:
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def update(self, entity: EmployerVerificationRequest) -> EmployerVerificationRequest:
        await self._session.flush()
        return entity

    async def get_by_employment_id(self, employment_id: UUID) -> EmployerVerificationRequest | None:
        stmt = select(EmployerVerificationRequest).where(
            EmployerVerificationRequest.employment_id == employment_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_public_id(self, public_id: UUID) -> EmployerVerificationRequest | None:
        stmt = select(EmployerVerificationRequest).where(
            EmployerVerificationRequest.public_id == public_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_verification_request_id(
        self,
        verification_request_id: UUID,
    ) -> EmployerVerificationRequest | None:
        stmt = select(EmployerVerificationRequest).where(
            EmployerVerificationRequest.verification_request_id == verification_request_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_token_hash(self, token_hash: str) -> EmployerVerificationRequest | None:
        stmt = (
            select(EmployerVerificationRequest)
            .where(EmployerVerificationRequest.token_hash == token_hash)
            .options(selectinload(EmployerVerificationRequest.employment))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_with_employment_owned(
        self,
        employment_id: UUID,
        owner_user_id: UUID,
    ) -> EmployerVerificationRequest | None:
        stmt = (
            select(EmployerVerificationRequest)
            .join(Employment, Employment.id == EmployerVerificationRequest.employment_id)
            .where(
                EmployerVerificationRequest.employment_id == employment_id,
                Employment.created_by_user_id == owner_user_id,
                Employment.deleted_at.is_(None),
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
