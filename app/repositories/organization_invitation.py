"""Repository for organization invitations."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.organization_invitation import OrganizationInvitation


class OrganizationInvitationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, invitation: OrganizationInvitation) -> OrganizationInvitation:
        self._session.add(invitation)
        await self._session.flush()
        return invitation

    async def get_by_public_id(self, invitation_public_id: UUID) -> OrganizationInvitation | None:
        stmt = (
            select(OrganizationInvitation)
            .options(
                joinedload(OrganizationInvitation.organization),
                joinedload(OrganizationInvitation.invited_by_user),
                joinedload(OrganizationInvitation.invitee_user),
            )
            .where(OrganizationInvitation.public_id == invitation_public_id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_invitee(self, *, invitee_email: str, invitee_user_id: UUID) -> list[OrganizationInvitation]:
        stmt = (
            select(OrganizationInvitation)
            .options(
                joinedload(OrganizationInvitation.organization),
                joinedload(OrganizationInvitation.invited_by_user),
                joinedload(OrganizationInvitation.invitee_user),
            )
            .where(
                or_(
                    OrganizationInvitation.invitee_email == invitee_email,
                    OrganizationInvitation.invitee_user_id == invitee_user_id,
                )
            )
            .order_by(OrganizationInvitation.created_at.desc())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())

    async def list_pending_for_invitee(
        self,
        *,
        invitee_email: str,
        invitee_user_id: UUID,
        now: datetime,
    ) -> list[OrganizationInvitation]:
        rows = await self.list_for_invitee(invitee_email=invitee_email, invitee_user_id=invitee_user_id)
        return [
            invitation
            for invitation in rows
            if invitation.accepted_at is None
            and invitation.declined_at is None
            and invitation.cancelled_at is None
            and (invitation.expires_at is None or invitation.expires_at > now)
        ]
