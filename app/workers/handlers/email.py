"""Email delivery worker handler."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.integrations.email.providers import get_email_provider
from app.models.notification_event import NotificationEvent
from app.models.trust_invitation_event import TrustInvitationEvent
from app.repositories.email_delivery_log import EmailDeliveryLogRepository
from app.repositories.notification import (
    NotificationDeliveryRepository,
    NotificationEventRepository,
)
from app.repositories.trust_invitation import TrustInvitationRepository
from app.schemas.email_delivery import EmailSendJobPayload
from app.trust_invitations.enums import TrustInvitationDeliveryState, TrustInvitationEventType
from app.workers.registry import register_handler

logger = logging.getLogger(__name__)


class EmailSendJobHandler:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        *,
        logs: EmailDeliveryLogRepository | None = None,
        deliveries: NotificationDeliveryRepository | None = None,
        notification_events: NotificationEventRepository | None = None,
        invitations: TrustInvitationRepository | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._logs = logs or EmailDeliveryLogRepository(session)
        self._deliveries = deliveries
        self._notification_events = notification_events
        self._invitations = invitations

    async def handle(self, data: dict[str, object]) -> None:
        payload = EmailSendJobPayload.model_validate(data)
        log = await self._logs.get_by_public_id(payload.email_delivery_log_public_id)
        if log is None:
            logger.warning(
                "email_delivery_log_not_found",
                extra={"event": "email_delivery_log_not_found"},
            )
            return
        if log.status in {"sent", "skipped"}:
            return

        now = datetime.now(tz=UTC)
        log.attempt_count = (log.attempt_count or 0) + 1
        try:
            result = await get_email_provider(self._settings).send(payload.message)
        except Exception as exc:
            log.status = "failed"
            log.failed_at = now
            log.error_code = type(exc).__name__
            log.error_message = str(exc)
            await self._reconcile_delivery_state(log)
            return

        log.provider = result.provider
        log.status = result.status
        log.provider_message_id = result.provider_message_id
        log.error_code = result.error_code
        log.error_message = result.error_message
        if result.status == "sent":
            log.sent_at = now
        if result.status == "failed":
            log.failed_at = now
        await self._reconcile_delivery_state(log)

    async def _reconcile_delivery_state(self, log) -> None:  # noqa: ANN001
        if self._session is None and (
            self._deliveries is None
            or self._notification_events is None
            or self._invitations is None
        ):
            return

        deliveries = self._deliveries or NotificationDeliveryRepository(self._session)
        notification_events = self._notification_events or NotificationEventRepository(
            self._session
        )
        invitations = self._invitations or TrustInvitationRepository(self._session)

        delivery = await deliveries.get_by_email_delivery_log_id(log.id)
        if delivery is None:
            return

        delivery.provider = log.provider
        delivery.status = log.status
        delivery.provider_message_id = log.provider_message_id
        delivery.attempt_count = log.attempt_count
        delivery.error_code = log.error_code
        delivery.error_message = log.error_message
        delivery.dispatched_at = delivery.dispatched_at or log.queued_at
        delivery.delivered_at = log.sent_at
        delivery.failed_at = log.failed_at

        notification = delivery.notification
        if notification is None:
            return

        notification.status = log.status
        if log.status == "sent":
            notification.sent_at = log.sent_at or log.queued_at
            notification.failed_at = None
            await notification_events.append(
                NotificationEvent(
                    notification_id=notification.id,
                    event_type="notification_dispatch_completed",
                    status=notification.status,
                    metadata_payload={"channel": delivery.channel, "provider": log.provider},
                )
            )
        elif log.status == "failed":
            notification.failed_at = log.failed_at or datetime.now(tz=UTC)
            await notification_events.append(
                NotificationEvent(
                    notification_id=notification.id,
                    event_type="notification_dispatch_failed",
                    status=notification.status,
                    metadata_payload={"channel": delivery.channel, "provider": log.provider},
                )
            )

        await self._reconcile_trust_invitation(notification.metadata_payload, log, invitations)

    async def _reconcile_trust_invitation(
        self,
        metadata: dict[str, object] | None,
        log,  # noqa: ANN001
        invitations: TrustInvitationRepository,
    ) -> None:
        if not metadata:
            return

        invitation_public_id = metadata.get("trust_invitation_public_id")
        if invitation_public_id is None:
            return

        try:
            invitation = await invitations.get_by_public_id(UUID(str(invitation_public_id)))
        except ValueError:
            return
        if invitation is None:
            return

        trigger_value = str(metadata.get("delivery_trigger", "")).strip().lower()
        trigger_event = (
            TrustInvitationEventType(trigger_value)
            if trigger_value
            in {
                TrustInvitationEventType.SENT.value,
                TrustInvitationEventType.RESENT.value,
            }
            else None
        )

        if log.status == "sent":
            invitation.delivery_state = TrustInvitationDeliveryState.DELIVERED
            invitation.sent_at = log.sent_at or log.queued_at
            if trigger_event is not None:
                await invitations.add_event(
                    TrustInvitationEvent(
                        invitation_id=invitation.id,
                        event_type=trigger_event.value,
                        metadata_payload={
                            "provider": log.provider,
                            "provider_message_id": log.provider_message_id,
                        },
                    )
                )
            return

        if log.status == "failed":
            if invitation.delivery_state != TrustInvitationDeliveryState.DELIVERED:
                invitation.delivery_state = TrustInvitationDeliveryState.FAILED
            await invitations.add_event(
                TrustInvitationEvent(
                    invitation_id=invitation.id,
                    event_type=TrustInvitationEventType.DELIVERY_FAILED.value,
                    metadata_payload={
                        "delivery_trigger": trigger_value or None,
                        "provider": log.provider,
                        "error_code": log.error_code,
                    },
                )
            )


@register_handler("email.send")
async def handle_email_send_job(data: dict[str, object], session: AsyncSession) -> None:
    await EmailSendJobHandler(session).handle(data)
