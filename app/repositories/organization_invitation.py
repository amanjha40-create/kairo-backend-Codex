"""Repository for organization invitations."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.organization_invitation import OrganizationInvitation
from app.organization.enums import OrganizationInvitationStatus


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

    async def get_by_public_id_for_organization(
        self,
        organization_id: UUID,
        invitation_public_id: UUID,
    ) -> OrganizationInvitation | None:
        stmt = (
            select(OrganizationInvitation)
            .options(
                joinedload(OrganizationInvitation.organization),
                joinedload(OrganizationInvitation.invited_by_user),
                joinedload(OrganizationInvitation.invitee_user),
            )
            .where(
                OrganizationInvitation.organization_id == organization_id,
                OrganizationInvitation.public_id == invitation_public_id,
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_invitee(
        self, *, invitee_email: str, invitee_user_id: UUID
    ) -> list[OrganizationInvitation]:
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

    async def list_for_organization(self, organization_id: UUID) -> list[OrganizationInvitation]:
        stmt = (
            select(OrganizationInvitation)
            .options(
                joinedload(OrganizationInvitation.organization),
                joinedload(OrganizationInvitation.invited_by_user),
                joinedload(OrganizationInvitation.invitee_user),
            )
            .where(OrganizationInvitation.organization_id == organization_id)
            .order_by(OrganizationInvitation.created_at.desc())
        )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())

    async def list_active_pending_for_organization_email(
        self,
        *,
        organization_id: UUID,
        invitee_email: str,
    ) -> list[OrganizationInvitation]:
        stmt = (
            select(OrganizationInvitation)
            .options(
                joinedload(OrganizationInvitation.organization),
                joinedload(OrganizationInvitation.invited_by_user),
                joinedload(OrganizationInvitation.invitee_user),
            )
            .where(
                OrganizationInvitation.organization_id == organization_id,
                func.lower(OrganizationInvitation.invitee_email) == invitee_email.lower(),
                OrganizationInvitation.status == OrganizationInvitationStatus.PENDING,
                OrganizationInvitation.accepted_at.is_(None),
                OrganizationInvitation.declined_at.is_(None),
                OrganizationInvitation.cancelled_at.is_(None),
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
        rows = await self.list_for_invitee(
            invitee_email=invitee_email, invitee_user_id=invitee_user_id
        )
        return [
            invitation
            for invitation in rows
            if invitation.accepted_at is None
            and invitation.declined_at is None
            and invitation.cancelled_at is None
            and (invitation.expires_at is None or invitation.expires_at > now)
        ]
