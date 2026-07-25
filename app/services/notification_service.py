"""Core notification center orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.exceptions import NotFoundError, ServiceUnavailableError
from app.models.notification import Notification
from app.models.notification_delivery import NotificationDelivery
from app.models.notification_event import NotificationEvent
from app.notifications.contracts import NotificationDispatchOutcome, NotificationRequest
from app.notifications.enums import NotificationStatus
from app.repositories.notification import (
    NotificationDeliveryRepository,
    NotificationEventRepository,
    NotificationRepository,
)
from app.schemas.pagination import ListQueryParams, Page, filter_sort_paginate
from app.schemas.notification import (
    NotificationDeliveryResponse,
    NotificationDetailResponse,
    NotificationEventResponse,
    NotificationResponse,
    NotificationStatisticsResponse,
    NotificationUnreadCountResponse,
    UserNotificationResponse,
)
from app.services.notification_channel_registry import NotificationChannelRegistry
from app.services.notification_dispatcher import NotificationDispatcher
from app.services.notification_email_channel import NotificationEmailChannel
from app.services.notification_preference_service import NotificationPreferenceService
from app.services.notification_template_resolver import NotificationTemplateResolver
from app.services.email_delivery_service import EmailDeliveryService


class NotificationService:
    """Creates, dispatches, tracks, and reports platform notifications."""

    _PRESENTATION_BY_EVENT: dict[str, tuple[str, str, str]] = {
        "verification_completed": (
            "verification",
            "Verification completed",
            "Your verification request has been completed.",
        ),
        "trust_invitation_created": (
            "verification",
            "Trust invitation",
            "You have received a Trust Passport verification invitation.",
        ),
        "password_reset_requested": (
            "security",
            "Password reset requested",
            "A password reset was requested for your Kairo account.",
        ),
    }

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        *,
        preferences: NotificationPreferenceService | None = None,
        template_resolver: NotificationTemplateResolver | None = None,
        channel_registry: NotificationChannelRegistry | None = None,
        dispatcher: NotificationDispatcher | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._notifications = NotificationRepository(session)
        self._deliveries = NotificationDeliveryRepository(session)
        self._events = NotificationEventRepository(session)
        self._preferences = preferences or NotificationPreferenceService(session)
        self._template_resolver = template_resolver or NotificationTemplateResolver()
        self._channel_registry = channel_registry or NotificationChannelRegistry(
            handlers=(
                NotificationEmailChannel(EmailDeliveryService(session, self._settings)),
            ),
        )
        self._dispatcher = dispatcher or NotificationDispatcher(self._channel_registry)

    async def create_and_dispatch(
        self,
        request: NotificationRequest,
        *,
        actor_user_id: UUID | None = None,
    ) -> NotificationDetailResponse:
        if request.dedupe_key:
            existing = await self._notifications.get_by_dedupe_key(request.dedupe_key)
            if existing is not None:
                return await self.get_detail(existing.public_id)
        template_key, template_version = self._template_resolver.resolve(request)
        category, title, body = self._presentation(request)
        preference = await self._preferences.evaluate(
            recipient_user_id=request.recipient_user_id,
            event_type=request.normalized_event_type(),
            requested_channel=request.channel,
        )
        notification = Notification(
            notification_type=request.notification_type.strip().lower(),
            event_type=request.normalized_event_type(),
            category=category,
            title=title,
            body=body,
            dedupe_key=request.dedupe_key,
            priority=request.priority.strip().lower(),
            status=NotificationStatus.PENDING.value,
            recipient_user_id=request.recipient_user_id,
            recipient_email=request.recipient_email,
            recipient_phone=request.recipient_phone,
            channel=preference.selected_channel,
            template_key=template_key,
            template_version=template_version,
            payload=request.payload,
            metadata_payload={
                **request.metadata,
                "preference_public_id": str(preference.matched_preference_public_id)
                if preference.matched_preference_public_id is not None
                else None,
            },
            scheduled_at=request.scheduled_at,
        )
        await self._notifications.create(notification)
        await self._append_event(
            notification,
            actor_user_id=actor_user_id,
            event_type="notification_created",
            status=notification.status,
            metadata={"channel": notification.channel, "event_type": notification.event_type},
        )

        if not preference.enabled:
            notification.status = NotificationStatus.SKIPPED.value
            await self._append_event(
                notification,
                actor_user_id=actor_user_id,
                event_type="notification_skipped",
                status=notification.status,
                metadata={"reason": "preferences_disabled"},
            )
            await self._session.commit()
            return await self.get_detail(notification.public_id)

        if notification.scheduled_at is not None and notification.scheduled_at > datetime.now(tz=UTC):
            await self._session.commit()
            return await self.get_detail(notification.public_id)

        await self._dispatch_notification(notification, actor_user_id=actor_user_id)
        await self._session.commit()
        return await self.get_detail(notification.public_id)

    @classmethod
    def _presentation(cls, request: NotificationRequest) -> tuple[str, str, str]:
        default = cls._PRESENTATION_BY_EVENT.get(request.normalized_event_type())
        if default is None:
            return request.category.strip().lower(), request.title.strip(), request.body.strip()
        category, default_title, default_body = default
        title = request.title.strip()
        body = request.body.strip()
        return category, default_title if title == "Kairo notification" else title, default_body if body == "You have a new notification." else body

    async def list_user_notifications(self, user_id: UUID, params: ListQueryParams) -> Page[UserNotificationResponse]:
        items = await self._notifications.list_for_user(user_id, offset=params.slice_start, limit=params.limit or 20)
        total = await self._notifications.count_for_user(user_id)
        return Page[UserNotificationResponse].create(
            items=[self._to_user_response(item) for item in items],
            total=total,
            params=params,
        )

    async def unread_count(self, user_id: UUID) -> NotificationUnreadCountResponse:
        return NotificationUnreadCountResponse(unread_count=await self._notifications.count_for_user(user_id, unread_only=True))

    async def mark_user_read(self, user_id: UUID, notification_public_id: UUID) -> None:
        if not await self._notifications.mark_read(user_id, notification_public_id):
            raise NotFoundError("Notification not found")
        await self._session.commit()

    async def mark_user_read_all(self, user_id: UUID) -> int:
        count = await self._notifications.mark_all_read(user_id)
        await self._session.commit()
        return count

    async def get_detail(self, notification_public_id: UUID) -> NotificationDetailResponse:
        notification = await self._require_notification(notification_public_id)
        deliveries = await self._deliveries.list_for_notification(notification.id)
        history = await self._events.list_for_notification(notification.id)
        return self._to_detail_response(notification, deliveries, history)

    async def list_notifications(
        self,
        params: ListQueryParams,
    ) -> Page[NotificationResponse]:
        items = [self._to_response(item) for item in await self._notifications.list_all()]
        page = filter_sort_paginate(
            items,
            params=params,
            search_fields=("event_type", "notification_type", "recipient_email", "channel", "status", "template_key"),
            allowed_sort_fields=("created_at", "updated_at", "event_type", "channel", "status", "priority"),
            default_sort_by="created_at",
            force_page_envelope=True,
        )
        if not isinstance(page, Page):
            raise RuntimeError("Notification list must return a page envelope")
        return page

    async def list_history(
        self,
        notification_public_id: UUID,
        params: ListQueryParams,
    ) -> Page[NotificationEventResponse]:
        notification = await self._require_notification(notification_public_id)
        items = [self._to_event_response(item) for item in await self._events.list_for_notification(notification.id)]
        page = filter_sort_paginate(
            items,
            params=params,
            search_fields=("event_type", "status"),
            allowed_sort_fields=("created_at", "event_type", "status"),
            default_sort_by="created_at",
            force_page_envelope=True,
        )
        if not isinstance(page, Page):
            raise RuntimeError("Notification history must return a page envelope")
        return page

    async def list_deliveries(
        self,
        notification_public_id: UUID,
        params: ListQueryParams,
    ) -> Page[NotificationDeliveryResponse]:
        notification = await self._require_notification(notification_public_id)
        items = [self._to_delivery_response(item) for item in await self._deliveries.list_for_notification(notification.id)]
        page = filter_sort_paginate(
            items,
            params=params,
            search_fields=("channel", "status", "provider", "error_code"),
            allowed_sort_fields=("created_at", "updated_at", "channel", "status", "attempt_count"),
            default_sort_by="created_at",
            force_page_envelope=True,
        )
        if not isinstance(page, Page):
            raise RuntimeError("Notification delivery history must return a page envelope")
        return page

    async def resend(
        self,
        notification_public_id: UUID,
        *,
        actor_user_id: UUID | None = None,
    ) -> NotificationDetailResponse:
        notification = await self._require_notification(notification_public_id)
        await self._append_event(
            notification,
            actor_user_id=actor_user_id,
            event_type="notification_resend_requested",
            status=notification.status,
            metadata={},
        )
        await self._dispatch_notification(notification, actor_user_id=actor_user_id)
        await self._session.commit()
        return await self.get_detail(notification.public_id)

    async def get_statistics(self) -> NotificationStatisticsResponse:
        notifications = await self._notifications.list_all()
        by_status = dict(await self._notifications.count_by_status())
        by_channel = dict(await self._notifications.count_by_channel())
        return NotificationStatisticsResponse(
            total_notifications=len(notifications),
            by_status=by_status,
            by_channel=by_channel,
        )

    async def _dispatch_notification(
        self,
        notification: Notification,
        *,
        actor_user_id: UUID | None,
    ) -> None:
        notification.status = NotificationStatus.QUEUED.value
        await self._append_event(
            notification,
            actor_user_id=actor_user_id,
            event_type="notification_dispatch_started",
            status=notification.status,
            metadata={"channel": notification.channel},
        )
        try:
            outcome = await self._dispatcher.dispatch(notification)
        except ServiceUnavailableError:
            notification.status = NotificationStatus.FAILED.value
            notification.failed_at = datetime.now(tz=UTC)
            await self._append_event(
                notification,
                actor_user_id=actor_user_id,
                event_type="notification_dispatch_failed",
                status=notification.status,
                metadata={"reason": "channel_unavailable", "channel": notification.channel},
            )
            raise
        await self._record_delivery(notification, outcome)
        self._apply_outcome(notification, outcome)
        await self._append_event(
            notification,
            actor_user_id=actor_user_id,
            event_type="notification_dispatch_completed" if notification.status == NotificationStatus.SENT.value else "notification_dispatch_failed",
            status=notification.status,
            metadata={"channel": notification.channel, "provider": outcome.provider},
        )

    async def _record_delivery(self, notification: Notification, outcome: NotificationDispatchOutcome) -> NotificationDelivery:
        delivery = NotificationDelivery(
            notification_id=notification.id,
            channel=notification.channel,
            status=outcome.status,
            provider=outcome.provider,
            provider_message_id=outcome.provider_message_id,
            email_delivery_log_id=outcome.external_reference_id,
            attempt_count=outcome.attempt_count,
            error_code=outcome.error_code,
            error_message=outcome.error_message,
            metadata_payload=outcome.metadata,
            dispatched_at=outcome.dispatched_at,
            delivered_at=outcome.delivered_at,
            failed_at=outcome.failed_at,
        )
        await self._deliveries.create(delivery)
        return delivery

    def _apply_outcome(self, notification: Notification, outcome: NotificationDispatchOutcome) -> None:
        notification.status = outcome.status
        if outcome.status == NotificationStatus.SENT.value:
            notification.sent_at = outcome.delivered_at or outcome.dispatched_at
            notification.failed_at = None
        elif outcome.status == NotificationStatus.FAILED.value:
            notification.failed_at = outcome.failed_at or outcome.dispatched_at

    async def _append_event(
        self,
        notification: Notification,
        *,
        actor_user_id: UUID | None,
        event_type: str,
        status: str | None,
        metadata: dict[str, object],
    ) -> NotificationEvent:
        return await self._events.append(
            NotificationEvent(
                notification_id=notification.id,
                actor_user_id=actor_user_id,
                event_type=event_type,
                status=status,
                metadata_payload=metadata,
            )
        )

    async def _require_notification(self, notification_public_id: UUID) -> Notification:
        notification = await self._notifications.get_by_public_id(notification_public_id)
        if notification is None:
            raise NotFoundError("Notification not found")
        return notification

    def _to_response(self, notification: Notification) -> NotificationResponse:
        return NotificationResponse(
            public_id=notification.public_id,
            notification_type=notification.notification_type,
            event_type=notification.event_type,
            category=notification.category,
            title=notification.title,
            body=notification.body,
            priority=notification.priority,
            status=notification.status,
            recipient_user_id=notification.recipient_user_id,
            recipient_email=notification.recipient_email,
            recipient_phone=notification.recipient_phone,
            channel=notification.channel,
            template_key=notification.template_key,
            template_version=notification.template_version,
            payload=notification.payload,
            metadata=notification.metadata_payload,
            scheduled_at=notification.scheduled_at,
            sent_at=notification.sent_at,
            failed_at=notification.failed_at,
            read_at=notification.read_at,
            created_at=notification.created_at,
            updated_at=notification.updated_at,
        )

    @staticmethod
    def _to_user_response(notification: Notification) -> UserNotificationResponse:
        return UserNotificationResponse(
            public_id=notification.public_id,
            category=notification.category,
            event_type=notification.event_type,
            title=notification.title,
            body=notification.body,
            metadata=notification.metadata_payload,
            read_at=notification.read_at,
            created_at=notification.created_at,
        )

    def _to_delivery_response(self, delivery: NotificationDelivery) -> NotificationDeliveryResponse:
        return NotificationDeliveryResponse(
            public_id=delivery.public_id,
            channel=delivery.channel,
            status=delivery.status,
            provider=delivery.provider,
            provider_message_id=delivery.provider_message_id,
            email_delivery_log_public_id=delivery.email_delivery_log.public_id if delivery.email_delivery_log is not None else None,
            attempt_count=delivery.attempt_count,
            error_code=delivery.error_code,
            error_message=delivery.error_message,
            metadata=delivery.metadata_payload,
            dispatched_at=delivery.dispatched_at,
            delivered_at=delivery.delivered_at,
            failed_at=delivery.failed_at,
            created_at=delivery.created_at,
            updated_at=delivery.updated_at,
        )

    def _to_event_response(self, event: NotificationEvent) -> NotificationEventResponse:
        return NotificationEventResponse(
            public_id=event.public_id,
            actor_user_id=event.actor_user_id,
            event_type=event.event_type,
            status=event.status,
            metadata=event.metadata_payload,
            created_at=event.created_at,
            updated_at=event.updated_at,
        )

    def _to_detail_response(
        self,
        notification: Notification,
        deliveries: list[NotificationDelivery],
        history: list[NotificationEvent],
    ) -> NotificationDetailResponse:
        return NotificationDetailResponse(
            **self._to_response(notification).model_dump(),
            deliveries=[self._to_delivery_response(item) for item in deliveries],
            history=[self._to_event_response(item) for item in history],
        )
