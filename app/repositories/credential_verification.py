"""Generic credential verification request persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.credential_verification_request import CredentialVerificationRequest


class CredentialVerificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: CredentialVerificationRequest) -> CredentialVerificationRequest:
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def update(self, entity: CredentialVerificationRequest) -> CredentialVerificationRequest:
        await self._session.flush()
        return entity

    async def get_by_subject(
        self, subject_type: str, subject_id: UUID,
    ) -> CredentialVerificationRequest | None:
        stmt = select(CredentialVerificationRequest).where(
            CredentialVerificationRequest.subject_type == subject_type,
            CredentialVerificationRequest.subject_id == subject_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_token_hash(self, token_hash: str) -> CredentialVerificationRequest | None:
        stmt = select(CredentialVerificationRequest).where(
            CredentialVerificationRequest.token_hash == token_hash,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()
