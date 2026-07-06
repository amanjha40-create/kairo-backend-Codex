"""Repository for trust invitations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.trust_invitation import TrustInvitation


class TrustInvitationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, invitation: TrustInvitation) -> TrustInvitation:
        self._session.add(invitation)
        await self._session.flush()
        return invitation

    async def get_by_public_id(self, invitation_public_id: UUID) -> TrustInvitation | None:
        stmt = (
            select(TrustInvitation)
            .options(joinedload(TrustInvitation.organization))
            .where(TrustInvitation.public_id == invitation_public_id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_token_hash(self, token_hash: str) -> TrustInvitation | None:
        stmt = (
            select(TrustInvitation)
            .options(joinedload(TrustInvitation.organization))
            .where(TrustInvitation.token_hash == token_hash)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_organization(self, organization_id: UUID) -> list[TrustInvitation]:
        stmt = (
            select(TrustInvitation)
            .options(joinedload(TrustInvitation.organization))
            .where(TrustInvitation.organization_id == organization_id)
            .order_by(TrustInvitation.created_at.desc())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())
