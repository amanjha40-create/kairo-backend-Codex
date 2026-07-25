"""Repository for trust invitations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.models.trust_invitation import TrustInvitation
from app.models.trust_invitation_event import TrustInvitationEvent


class TrustInvitationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, invitation: TrustInvitation) -> TrustInvitation:
        self._session.add(invitation)
        await self._session.flush()
        return invitation

    async def add_event(self, event: TrustInvitationEvent) -> TrustInvitationEvent:
        self._session.add(event)
        await self._session.flush()
        return event

    async def delete(self, invitation: TrustInvitation) -> None:
        await self._session.delete(invitation)
        await self._session.flush()

    async def get_by_public_id(
        self,
        invitation_public_id: UUID,
        *,
        include_events: bool = False,
    ) -> TrustInvitation | None:
        options = [
            joinedload(TrustInvitation.organization),
            joinedload(TrustInvitation.created_by_user),
            joinedload(TrustInvitation.accepted_by_user),
            selectinload(TrustInvitation.verification_requests),
        ]
        if include_events:
            options.append(
                selectinload(TrustInvitation.events).joinedload(TrustInvitationEvent.actor_user),
            )
        stmt = (
            select(TrustInvitation)
            .options(*options)
            .where(TrustInvitation.public_id == invitation_public_id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_token_hash(self, token_hash: str, *, include_events: bool = False) -> TrustInvitation | None:
        options = [
            joinedload(TrustInvitation.organization),
            joinedload(TrustInvitation.created_by_user),
            joinedload(TrustInvitation.accepted_by_user),
            selectinload(TrustInvitation.verification_requests),
        ]
        if include_events:
            options.append(
                selectinload(TrustInvitation.events).joinedload(TrustInvitationEvent.actor_user),
            )
        stmt = (
            select(TrustInvitation)
            .options(*options)
            .where(TrustInvitation.token_hash == token_hash)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_organization(self, organization_id: UUID) -> list[TrustInvitation]:
        stmt = (
            select(TrustInvitation)
            .options(
                joinedload(TrustInvitation.organization),
                joinedload(TrustInvitation.created_by_user),
                joinedload(TrustInvitation.accepted_by_user),
                selectinload(TrustInvitation.verification_requests),
            )
            .where(TrustInvitation.organization_id == organization_id)
            .order_by(TrustInvitation.created_at.desc())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())
