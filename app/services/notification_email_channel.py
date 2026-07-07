"""Email channel handler for notification center."""

from __future__ import annotations

from datetime import UTC, datetime

from app.models.notification import Notification
from app.notifications.contracts import NotificationChannelHandler, NotificationDispatchOutcome
from app.notifications.enums import NotificationChannel, NotificationStatus
from app.services.email_delivery_service import EmailDeliveryService


class NotificationEmailChannel(NotificationChannelHandler):
    """Dispatches notification records through the existing email delivery stack."""

    channel_key = NotificationChannel.EMAIL.value

    def __init__(self, email_delivery: EmailDeliveryService) -> None:
        self._email_delivery = email_delivery

    async def send(self, notification: Notification) -> NotificationDispatchOutcome:
        if not notification.recipient_email:
            return NotificationDispatchOutcome(
                status=NotificationStatus.FAILED.value,
                error_code="recipient_missing",
                error_message="Notification is missing recipient_email for email channel dispatch",
                failed_at=datetime.now(tz=UTC),
            )

        log = await self._email_delivery.queue_template_email(
            template_key=notification.template_key,
            to_email=notification.recipient_email,
            template_data=notification.payload,
            recipient_user_id=notification.recipient_user_id,
        )
        normalized_status = self._normalize_status(log.status)
        return NotificationDispatchOutcome(
            status=normalized_status,
            provider=log.provider,
            provider_message_id=log.provider_message_id,
            external_reference_id=log.id,
            error_code=log.error_code,
            error_message=log.error_message,
            metadata={
                "email_delivery_log_public_id": str(log.public_id),
                "job_type": log.job_type,
            },
            dispatched_at=log.queued_at,
            delivered_at=log.sent_at,
            failed_at=log.failed_at,
            attempt_count=max(log.attempt_count, 1),
        )

    def _normalize_status(self, status: str) -> str:
        normalized = status.strip().lower()
        if normalized in {
            NotificationStatus.QUEUED.value,
            NotificationStatus.SENT.value,
            NotificationStatus.FAILED.value,
            NotificationStatus.SKIPPED.value,
        }:
            return normalized
        return NotificationStatus.QUEUED.value
