"""Public institution verification request persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.institution_verification_request import InstitutionVerificationRequest
from app.repositories.base import BaseRepository


class InstitutionVerificationRepository(BaseRepository[InstitutionVerificationRequest]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, InstitutionVerificationRequest)

    async def create(
        self,
        entity: InstitutionVerificationRequest,
    ) -> InstitutionVerificationRequest:
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def update(
        self,
        entity: InstitutionVerificationRequest,
    ) -> InstitutionVerificationRequest:
        await self._session.flush()
        return entity

    async def get_by_verification_request_id(
        self,
        verification_request_id: UUID,
    ) -> InstitutionVerificationRequest | None:
        stmt = select(InstitutionVerificationRequest).where(
            InstitutionVerificationRequest.verification_request_id == verification_request_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_token_hash(self, token_hash: str) -> InstitutionVerificationRequest | None:
        stmt = select(InstitutionVerificationRequest).where(
            InstitutionVerificationRequest.token_hash == token_hash,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()
