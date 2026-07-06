"""Trust invitation engine use cases."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import hash_refresh_token
from app.config import Settings
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.trust_invitation import TrustInvitation
from app.organization.enums import OrganizationRole
from app.repositories.trust_invitation import TrustInvitationRepository
from app.schemas.trust_invitation import (
    TrustInvitationAcceptResponse,
    TrustInvitationCreateRequest,
    TrustInvitationCreateResponse,
    TrustInvitationPublicLookupResponse,
    TrustInvitationResponse,
)
from app.services.organization_service import OrganizationService
from app.trust_invitations.enums import TrustInvitationStatus


class TrustInvitationService:
    """Organization-issued trust invitations with public token resolution."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._repo = TrustInvitationRepository(session)
        self._organizations = OrganizationService(session)

    async def create(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        payload: TrustInvitationCreateRequest,
    ) -> TrustInvitationCreateResponse:
        organization, _ = await self._organizations.require_org_member(actor_user_id, org_public_id)
        raw_token = secrets.token_urlsafe(32)
        invitation = TrustInvitation(
            organization_id=organization.id,
            subject_name=payload.subject_name,
            subject_email=self._normalize_email(str(payload.subject_email)),
            token_hash=hash_refresh_token(raw_token),
            status=TrustInvitationStatus.PENDING,
            created_by_user_id=actor_user_id,
            expires_at=payload.expires_at,
        )
        await self._repo.create(invitation)
        await self._session.commit()
        await self._session.refresh(invitation)
        refreshed = await self._repo.get_by_public_id(invitation.public_id)
        if refreshed is None:
            raise NotFoundError("Trust invitation not found")
        response = self._to_response(refreshed)
        return TrustInvitationCreateResponse(
            **response.model_dump(),
            invitation_url=self._build_invitation_url(raw_token),
        )

    async def list_for_organization(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
    ) -> list[TrustInvitationResponse]:
        organization, _ = await self._organizations.require_org_member(actor_user_id, org_public_id)
        invitations = await self._repo.list_for_organization(organization.id)
        return [self._to_response(invitation) for invitation in invitations]

    async def get_public_by_token(self, raw_token: str) -> TrustInvitationPublicLookupResponse:
        invitation = await self._resolve_active_token(raw_token)
        return TrustInvitationPublicLookupResponse(
            public_id=invitation.public_id,
            organization_name=invitation.organization.name,
            subject_name=invitation.subject_name,
            expires_at=invitation.expires_at,
            status=invitation.status,
        )

    async def accept(self, raw_token: str, actor_user_id: UUID, actor_email: str) -> TrustInvitationAcceptResponse:
        invitation = await self._resolve_active_token(raw_token)
        if self._normalize_email(actor_email) != invitation.subject_email:
            raise ForbiddenError("This trust invitation is not assigned to the authenticated account")

        invitation.status = TrustInvitationStatus.ACCEPTED
        invitation.accepted_by_user_id = actor_user_id
        invitation.accepted_at = datetime.now(tz=UTC)
        await self._session.commit()
        await self._session.refresh(invitation)
        refreshed = await self._repo.get_by_public_id(invitation.public_id)
        if refreshed is None or refreshed.accepted_at is None:
            raise NotFoundError("Trust invitation not found")
        return TrustInvitationAcceptResponse(
            public_id=refreshed.public_id,
            organization_public_id=refreshed.organization.public_id,
            status=refreshed.status,
            accepted_at=refreshed.accepted_at,
        )

    async def cancel(self, actor_user_id: UUID, invitation_public_id: UUID) -> TrustInvitationResponse:
        invitation = await self._repo.get_by_public_id(invitation_public_id)
        if invitation is None:
            raise NotFoundError("Trust invitation not found")

        _, actor_membership = await self._organizations.require_org_member(
            actor_user_id,
            invitation.organization.public_id,
        )
        if actor_membership.role not in {OrganizationRole.OWNER, OrganizationRole.ADMIN}:
            raise ForbiddenError("Only organization owners or admins can cancel trust invitations")
        if invitation.status == TrustInvitationStatus.ACCEPTED:
            raise ConflictError("Accepted trust invitations cannot be cancelled")
        if invitation.status == TrustInvitationStatus.CANCELLED:
            return self._to_response(invitation)

        invitation.status = TrustInvitationStatus.CANCELLED
        invitation.cancelled_at = datetime.now(tz=UTC)
        await self._session.commit()
        await self._session.refresh(invitation)
        refreshed = await self._repo.get_by_public_id(invitation.public_id)
        if refreshed is None:
            raise NotFoundError("Trust invitation not found")
        return self._to_response(refreshed)

    async def _resolve_active_token(self, raw_token: str) -> TrustInvitation:
        if not raw_token or len(raw_token) < 16:
            raise NotFoundError("Trust invitation not found")
        invitation = await self._repo.get_by_token_hash(hash_refresh_token(raw_token))
        if invitation is None:
            raise NotFoundError("Trust invitation not found")
        if invitation.status != TrustInvitationStatus.PENDING:
            raise NotFoundError("Trust invitation not found")
        if invitation.cancelled_at is not None or invitation.accepted_at is not None:
            raise NotFoundError("Trust invitation not found")
        if invitation.expires_at <= datetime.now(tz=UTC):
            raise NotFoundError("Trust invitation not found")
        return invitation

    def _to_response(self, invitation: TrustInvitation) -> TrustInvitationResponse:
        return TrustInvitationResponse(
            public_id=invitation.public_id,
            organization_public_id=invitation.organization.public_id,
            subject_name=invitation.subject_name,
            subject_email=invitation.subject_email,
            status=invitation.status,
            expires_at=invitation.expires_at,
            accepted_at=invitation.accepted_at,
            cancelled_at=invitation.cancelled_at,
            created_at=invitation.created_at,
            updated_at=invitation.updated_at,
        )

    def _build_invitation_url(self, raw_token: str) -> str:
        base = self._settings.app_public_base_url.rstrip("/")
        prefix = self._settings.api_v1_prefix.rstrip("/")
        return f"{base}{prefix}/trust-invitations/{raw_token}"

    def _normalize_email(self, email: str) -> str:
        return email.strip().lower()
