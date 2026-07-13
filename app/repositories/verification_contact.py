"""Persistence for versioned verification contacts."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.verification_contact import VerificationContact


class VerificationContactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, contact: VerificationContact) -> VerificationContact:
        self._session.add(contact)
        await self._session.flush()
        return contact

    async def get_current(self, verification_request_id: UUID) -> VerificationContact | None:
        stmt = select(VerificationContact).where(
            VerificationContact.verification_request_id == verification_request_id,
            VerificationContact.superseded_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_versions(self, verification_request_id: UUID) -> list[VerificationContact]:
        stmt = (
            select(VerificationContact)
            .where(VerificationContact.verification_request_id == verification_request_id)
            .order_by(VerificationContact.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())
