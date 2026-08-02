"""Trust invitation engine use cases."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import hash_refresh_token
from app.config import Settings
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.trust_invitation import TrustInvitation
from app.models.trust_invitation_event import TrustInvitationEvent
from app.notifications.contracts import NotificationRequest
from app.organization.permissions import is_organization_manager
from app.repositories.trust_invitation import TrustInvitationRepository
from app.schemas.pagination import ListQueryParams, Page, filter_sort_paginate
from app.schemas.trust_invitation import (
    TrustInvitationAcceptResponse,
    TrustInvitationCreateRequest,
    TrustInvitationCreateResponse,
    TrustInvitationDetailResponse,
    TrustInvitationPublicLookupResponse,
    TrustInvitationResponse,
    TrustInvitationSummaryResponse,
    TrustInvitationTimelineEventResponse,
)
from app.services.notification_service import NotificationService
from app.services.organization_person_service import OrganizationPersonService
from app.services.organization_service import OrganizationService
from app.trust_invitations.enums import (
    TrustInvitationDeliveryState,
    TrustInvitationEventType,
    TrustInvitationStatus,
    TrustInvitationVerificationType,
)

logger = logging.getLogger(__name__)


class TrustInvitationService:
    """Organization-issued trust invitations with public token resolution."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        repo: TrustInvitationRepository | None = None,
        organizations: OrganizationService | None = None,
        notifications: NotificationService | None = None,
        people: OrganizationPersonService | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._repo = repo or TrustInvitationRepository(session)
        self._organizations = organizations or OrganizationService(session)
        self._notifications = notifications or NotificationService(session, settings)
        self._people = people or OrganizationPersonService(session, settings)

    async def create(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        payload: TrustInvitationCreateRequest,
    ) -> TrustInvitationCreateResponse:
        organization, _ = await self._organizations.require_org_member(actor_user_id, org_public_id)
        invitation_public_id = secrets.token_hex(16)
        invitation_uuid = UUID(hex=invitation_public_id)
        signed_token = self._build_signed_token(invitation_uuid)
        invitation = TrustInvitation(
            public_id=invitation_uuid,
            organization_id=organization.id,
            subject_name=payload.subject_name,
            subject_email=self._normalize_email(str(payload.subject_email)),
            subject_phone=payload.subject_phone,
            purpose=payload.purpose,
            requested_verification_types=[item.value for item in payload.requested_verification_types],
            message=payload.message,
            token_hash=hash_refresh_token(signed_token),
            status=TrustInvitationStatus.DRAFT if payload.mode == "draft" else TrustInvitationStatus.PENDING,
            delivery_method=payload.delivery_method,
            delivery_state=TrustInvitationDeliveryState.QUEUED,
            created_by_user_id=actor_user_id,
            expires_at=payload.expires_at,
            sent_at=datetime.now(tz=UTC) if payload.mode == "send" else None,
        )
        await self._repo.create(invitation)
        await self._record_event(invitation, TrustInvitationEventType.CREATED, actor_user_id=actor_user_id)
        if payload.mode == "send":
            await self._record_event(invitation, TrustInvitationEventType.SENT, actor_user_id=actor_user_id)
        await self._session.commit()

        refreshed = await self._repo.get_by_public_id(invitation.public_id, include_events=True)
        if refreshed is None:
            raise NotFoundError("Trust invitation not found")
        await self._sync_person_link_best_effort(refreshed, actor_user_id=actor_user_id)
        refreshed = await self._repo.get_by_public_id(invitation.public_id, include_events=True)
        if refreshed is None:
            raise NotFoundError("Trust invitation not found")

        if payload.mode == "send":
            await self._deliver_invitation(
                refreshed,
                actor_user_id=actor_user_id,
                trigger_event=TrustInvitationEventType.SENT,
                record_event=False,
            )
            await self._session.commit()
            refreshed = await self._repo.get_by_public_id(invitation.public_id, include_events=True)
            if refreshed is None:
                raise NotFoundError("Trust invitation not found")

        return TrustInvitationCreateResponse(
            **self._to_response(refreshed).model_dump(),
            invitation_url=self._build_invitation_url(refreshed.public_id),
        )

    async def get_detail(
        self,
        actor_user_id: UUID,
        invitation_public_id: UUID,
    ) -> TrustInvitationDetailResponse:
        invitation = await self._require_member_visible_invitation(
            actor_user_id,
            invitation_public_id,
            include_events=True,
        )
        changed = await self._expire_if_needed(invitation)
        if changed:
            await self._session.commit()
            invitation = await self._repo.get_by_public_id(invitation_public_id, include_events=True)
            if invitation is None:
                raise NotFoundError("Trust invitation not found")
        return self._to_detail_response(invitation)

    async def get_summary(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
    ) -> TrustInvitationSummaryResponse:
        organization, _ = await self._organizations.require_org_member(actor_user_id, org_public_id)
        invitations = await self._repo.list_for_organization(organization.id)
        changed = await self._expire_many(invitations)
        if changed:
            await self._session.commit()
            invitations = await self._repo.list_for_organization(organization.id)

        now = datetime.now(tz=UTC)
        expiring_cutoff = now + timedelta(days=2)
        return TrustInvitationSummaryResponse(
            active_count=sum(1 for invitation in invitations if invitation.status == TrustInvitationStatus.PENDING),
            accepted_count=sum(1 for invitation in invitations if invitation.status == TrustInvitationStatus.ACCEPTED),
            cancelled_count=sum(1 for invitation in invitations if invitation.status == TrustInvitationStatus.CANCELLED),
            expiring_soon_count=sum(
                1
                for invitation in invitations
                if invitation.status == TrustInvitationStatus.PENDING and invitation.expires_at <= expiring_cutoff
            ),
            draft_count=sum(1 for invitation in invitations if invitation.status == TrustInvitationStatus.DRAFT),
        )

    async def list_for_organization(
        self,
        actor_user_id: UUID,
        org_public_id: UUID,
        params: ListQueryParams | None = None,
    ) -> list[TrustInvitationResponse] | Page[TrustInvitationResponse]:
        organization, _ = await self._organizations.require_org_member(actor_user_id, org_public_id)
        invitations = await self._repo.list_for_organization(organization.id)
        changed = await self._expire_many(invitations)
        if changed:
            await self._session.commit()
            invitations = await self._repo.list_for_organization(organization.id)
        responses = [self._to_response(invitation) for invitation in invitations]
        if params is None:
            return responses
        return filter_sort_paginate(
            responses,
            params=params,
            search_fields=("subject_name", "subject_email", "purpose", "status", "delivery_state"),
            allowed_sort_fields=(
                "created_at",
                "updated_at",
                "expires_at",
                "subject_name",
                "subject_email",
                "purpose",
                "status",
                "delivery_state",
                "sent_at",
                "opened_at",
            ),
            default_sort_by="created_at",
        )

    async def send(self, actor_user_id: UUID, invitation_public_id: UUID) -> TrustInvitationDetailResponse:
        invitation = await self._require_member_visible_invitation(
            actor_user_id,
            invitation_public_id,
            include_events=True,
        )
        await self._expire_or_raise_non_actionable(invitation)
        if invitation.status != TrustInvitationStatus.DRAFT:
            raise ConflictError("Only draft trust invitations can be sent")

        invitation.status = TrustInvitationStatus.PENDING
        invitation.sent_at = datetime.now(tz=UTC)
        await self._record_event(invitation, TrustInvitationEventType.SENT, actor_user_id=actor_user_id)
        await self._deliver_invitation(
            invitation,
            actor_user_id=actor_user_id,
            trigger_event=TrustInvitationEventType.SENT,
            record_event=False,
        )
        await self._session.commit()

        refreshed = await self._repo.get_by_public_id(invitation_public_id, include_events=True)
        if refreshed is None:
            raise NotFoundError("Trust invitation not found")
        return self._to_detail_response(refreshed)

    async def resend(self, actor_user_id: UUID, invitation_public_id: UUID) -> TrustInvitationDetailResponse:
        invitation = await self._require_member_visible_invitation(
            actor_user_id,
            invitation_public_id,
            include_events=True,
        )
        await self._expire_or_raise_non_actionable(invitation)
        if invitation.status == TrustInvitationStatus.DRAFT:
            raise ConflictError("Draft trust invitations must be sent before they can be resent")

        await self._record_event(invitation, TrustInvitationEventType.RESENT, actor_user_id=actor_user_id)
        await self._deliver_invitation(
            invitation,
            actor_user_id=actor_user_id,
            trigger_event=TrustInvitationEventType.RESENT,
            record_event=False,
        )
        await self._session.commit()

        refreshed = await self._repo.get_by_public_id(invitation_public_id, include_events=True)
        if refreshed is None:
            raise NotFoundError("Trust invitation not found")
        return self._to_detail_response(refreshed)

    async def delete(self, actor_user_id: UUID, invitation_public_id: UUID) -> None:
        invitation = await self._require_member_visible_invitation(actor_user_id, invitation_public_id)
        if invitation.status != TrustInvitationStatus.DRAFT:
            raise ConflictError("Only draft trust invitations can be deleted")
        await self._repo.delete(invitation)
        await self._session.commit()

    async def get_public_by_token(self, raw_token: str) -> TrustInvitationPublicLookupResponse:
        invitation = await self._resolve_active_token(raw_token)
        changed = False
        if invitation.opened_at is None:
            invitation.opened_at = datetime.now(tz=UTC)
            invitation.delivery_state = TrustInvitationDeliveryState.OPENED
            await self._record_event(invitation, TrustInvitationEventType.OPENED)
            changed = True
        if changed:
            await self._session.commit()
            invitation = await self._repo.get_by_public_id(invitation.public_id)
            if invitation is None:
                raise NotFoundError("Trust invitation not found")
        return TrustInvitationPublicLookupResponse(
            public_id=invitation.public_id,
            organization_name=invitation.organization.name,
            subject_name=invitation.subject_name,
            purpose=invitation.purpose,
            requested_verification_types=self._deserialize_verification_types(invitation.requested_verification_types),
            expires_at=invitation.expires_at,
            status=invitation.status,
        )

    async def accept(self, raw_token: str, actor_user_id: UUID, actor_email: str) -> TrustInvitationAcceptResponse:
        invitation = await self._resolve_active_token(raw_token)
        if self._normalize_email(actor_email) != invitation.subject_email:
            raise ForbiddenError("This trust invitation is not assigned to the authenticated account")

        now = datetime.now(tz=UTC)
        if invitation.opened_at is None:
            invitation.opened_at = now
            invitation.delivery_state = TrustInvitationDeliveryState.OPENED
            await self._record_event(invitation, TrustInvitationEventType.OPENED, actor_user_id=actor_user_id)

        invitation.status = TrustInvitationStatus.ACCEPTED
        invitation.accepted_by_user_id = actor_user_id
        invitation.accepted_at = now
        await self._record_event(invitation, TrustInvitationEventType.ACCEPTED, actor_user_id=actor_user_id)
        await self._session.commit()
        await self._sync_person_link_best_effort(invitation, actor_user_id=actor_user_id)

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
        invitation = await self._require_member_visible_invitation(actor_user_id, invitation_public_id)
        _, actor_membership = await self._organizations.require_org_member(
            actor_user_id,
            invitation.organization.public_id,
        )
        if not is_organization_manager(actor_membership.role):
            raise ForbiddenError("Only organization owners or admins can cancel trust invitations")

        await self._expire_or_raise_non_actionable(invitation)
        if invitation.status == TrustInvitationStatus.ACCEPTED:
            raise ConflictError("Accepted trust invitations cannot be cancelled")
        if invitation.status == TrustInvitationStatus.CANCELLED:
            return self._to_response(invitation)

        invitation.status = TrustInvitationStatus.CANCELLED
        invitation.cancelled_at = datetime.now(tz=UTC)
        await self._record_event(invitation, TrustInvitationEventType.CANCELLED, actor_user_id=actor_user_id)
        await self._session.commit()

        refreshed = await self._repo.get_by_public_id(invitation.public_id)
        if refreshed is None:
            raise NotFoundError("Trust invitation not found")
        return self._to_response(refreshed)

    async def _require_member_visible_invitation(
        self,
        actor_user_id: UUID,
        invitation_public_id: UUID,
        *,
        include_events: bool = False,
    ) -> TrustInvitation:
        invitation = await self._repo.get_by_public_id(invitation_public_id, include_events=include_events)
        if invitation is None:
            raise NotFoundError("Trust invitation not found")
        await self._organizations.require_org_member(actor_user_id, invitation.organization.public_id)
        return invitation

    async def _resolve_active_token(self, raw_token: str) -> TrustInvitation:
        if not raw_token or len(raw_token) < 16:
            raise NotFoundError("Trust invitation not found")

        invitation: TrustInvitation | None
        signed_public_id = self._verify_signed_token(raw_token)
        if signed_public_id is not None:
            invitation = await self._repo.get_by_public_id(signed_public_id)
        else:
            invitation = await self._repo.get_by_token_hash(hash_refresh_token(raw_token))

        if invitation is None:
            raise NotFoundError("Trust invitation not found")

        expired = await self._expire_if_needed(invitation)
        if expired:
            await self._session.commit()
            raise NotFoundError("Trust invitation not found")

        if invitation.status not in {TrustInvitationStatus.DRAFT, TrustInvitationStatus.PENDING}:
            raise NotFoundError("Trust invitation not found")
        if invitation.cancelled_at is not None or invitation.accepted_at is not None:
            raise NotFoundError("Trust invitation not found")
        return invitation

    async def _expire_or_raise_non_actionable(self, invitation: TrustInvitation) -> None:
        expired = await self._expire_if_needed(invitation)
        if expired or invitation.status == TrustInvitationStatus.EXPIRED:
            await self._session.commit()
            raise ConflictError("Expired trust invitations are no longer actionable")
        if invitation.status == TrustInvitationStatus.CANCELLED:
            raise ConflictError("Cancelled trust invitations are no longer actionable")

    async def _expire_many(self, invitations: list[TrustInvitation]) -> bool:
        changed = False
        for invitation in invitations:
            changed = await self._expire_if_needed(invitation) or changed
        return changed

    async def _expire_if_needed(self, invitation: TrustInvitation) -> bool:
        if invitation.status in {
            TrustInvitationStatus.ACCEPTED,
            TrustInvitationStatus.CANCELLED,
            TrustInvitationStatus.EXPIRED,
        }:
            return False
        if invitation.expires_at > datetime.now(tz=UTC):
            return False

        invitation.status = TrustInvitationStatus.EXPIRED
        await self._record_event(invitation, TrustInvitationEventType.EXPIRED)
        return True

    async def _deliver_invitation(
        self,
        invitation: TrustInvitation,
        *,
        actor_user_id: UUID | None,
        trigger_event: TrustInvitationEventType,
        record_event: bool,
    ) -> None:
        if record_event:
            await self._record_event(invitation, trigger_event, actor_user_id=actor_user_id)

        invitation_url = self._build_invitation_url(invitation.public_id)
        try:
            await self._notifications.create_and_dispatch(
                NotificationRequest(
                    event_type="trust_invitation_created",
                    recipient_email=invitation.subject_email,
                    payload={
                        "organization_name": invitation.organization.name,
                        "subject_name": invitation.subject_name,
                        "invitation_url": invitation_url,
                        "expires_at_iso": invitation.expires_at.isoformat(),
                        "purpose": invitation.purpose,
                    },
                    metadata={
                        "trust_invitation_public_id": str(invitation.public_id),
                        "organization_public_id": str(invitation.organization.public_id),
                        "delivery_trigger": trigger_event.value,
                    },
                ),
                actor_user_id=actor_user_id,
            )
            if invitation.delivery_state != TrustInvitationDeliveryState.OPENED:
                invitation.delivery_state = TrustInvitationDeliveryState.DELIVERED
        except Exception as exc:
            invitation.delivery_state = TrustInvitationDeliveryState.FAILED
            await self._record_event(
                invitation,
                TrustInvitationEventType.DELIVERY_FAILED,
                actor_user_id=actor_user_id,
                metadata={
                    "delivery_trigger": trigger_event.value,
                    "error_type": type(exc).__name__,
                },
            )
            logger.warning(
                "trust_invitation_notification_delivery_failed",
                extra={
                    "event": "trust_invitation_notification_delivery_failed",
                    "invitation_public_id": str(invitation.public_id),
                    "delivery_trigger": trigger_event.value,
                    "error_type": type(exc).__name__,
                },
            )

    async def _record_event(
        self,
        invitation: TrustInvitation,
        event_type: TrustInvitationEventType,
        *,
        actor_user_id: UUID | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        await self._repo.add_event(
            TrustInvitationEvent(
                invitation_id=invitation.id,
                event_type=event_type.value,
                actor_user_id=actor_user_id,
                metadata_payload=metadata or {},
            )
        )

    async def _sync_person_link_best_effort(
        self,
        invitation: TrustInvitation,
        *,
        actor_user_id: UUID | None,
    ) -> None:
        try:
            await self._people.resolve_for_trust_invitation(invitation, actor_user_id=actor_user_id)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            logger.warning(
                "trust_invitation_person_sync_failed",
                extra={
                    "event": "trust_invitation_person_sync_failed",
                    "invitation_public_id": str(invitation.public_id),
                    "actor_user_id": str(actor_user_id) if actor_user_id is not None else None,
                },
            )

    def _to_response(self, invitation: TrustInvitation) -> TrustInvitationResponse:
        return TrustInvitationResponse(
            public_id=invitation.public_id,
            organization_public_id=invitation.organization.public_id,
            subject_name=invitation.subject_name,
            subject_email=invitation.subject_email,
            subject_phone=invitation.subject_phone,
            purpose=invitation.purpose,
            requested_verification_types=self._deserialize_verification_types(invitation.requested_verification_types),
            message=invitation.message,
            status=invitation.status,
            delivery_method=invitation.delivery_method,
            delivery_state=invitation.delivery_state,
            created_by_email=invitation.created_by_user.email,
            created_by_full_name=invitation.created_by_user.full_name,
            expires_at=invitation.expires_at,
            sent_at=invitation.sent_at,
            opened_at=invitation.opened_at,
            accepted_at=invitation.accepted_at,
            cancelled_at=invitation.cancelled_at,
            related_verification_request_public_id=self._related_verification_request_public_id(invitation),
            created_at=invitation.created_at,
            updated_at=invitation.updated_at,
        )

    def _to_detail_response(self, invitation: TrustInvitation) -> TrustInvitationDetailResponse:
        return TrustInvitationDetailResponse(
            **self._to_response(invitation).model_dump(),
            invitation_url=self._build_invitation_url(invitation.public_id),
            timeline=[
                TrustInvitationTimelineEventResponse(
                    id=event.id,
                    event_type=TrustInvitationEventType(event.event_type),
                    occurred_at=event.occurred_at,
                    actor_user_id=event.actor_user_id,
                    actor_email=event.actor_user.email if event.actor_user is not None else None,
                    actor_full_name=event.actor_user.full_name if event.actor_user is not None else None,
                    metadata=event.metadata_payload,
                )
                for event in invitation.events
            ],
        )

    def _related_verification_request_public_id(self, invitation: TrustInvitation) -> UUID | None:
        if not invitation.verification_requests:
            return None
        return invitation.verification_requests[0].public_id

    def _deserialize_verification_types(self, values: list[str]) -> list[TrustInvitationVerificationType]:
        return [TrustInvitationVerificationType(value) for value in values]

    def _build_invitation_url(self, invitation_public_id: UUID) -> str:
        base = self._settings.app_public_base_url.rstrip("/")
        token = self._build_signed_token(invitation_public_id)
        # APP_PUBLIC_BASE_URL is the Candidate web origin. Public lookup and
        # acceptance remain API endpoints behind this human-facing route.
        return f"{base}/trust-invitations/{token}"

    def _build_signed_token(self, invitation_public_id: UUID) -> str:
        body = invitation_public_id.hex
        signature = hmac.new(
            self._settings.jwt_secret_key.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"v2.{body}.{signature}"

    def _verify_signed_token(self, raw_token: str) -> UUID | None:
        prefix, separator, remainder = raw_token.partition(".")
        if prefix != "v2" or not separator:
            return None
        body, separator, signature = remainder.partition(".")
        if not separator or len(body) != 32 or not signature:
            return None
        try:
            invitation_public_id = UUID(hex=body)
        except ValueError:
            return None

        expected = hmac.new(
            self._settings.jwt_secret_key.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        return invitation_public_id

    def _normalize_email(self, email: str) -> str:
        return email.strip().lower()
