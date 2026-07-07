"""Unit tests for notification center orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.config import Settings
from app.exceptions import ServiceUnavailableError
from app.models.notification_delivery import NotificationDelivery
from app.models.notification_event import NotificationEvent
from app.notifications.contracts import (
    NotificationDispatchOutcome,
    NotificationPreferenceDecision,
    NotificationRequest,
)
from app.notifications.enums import NotificationStatus
from app.services.notification_service import NotificationService


def _settings(**overrides: object) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        "jwt_secret_key": "test-jwt-secret-key-32-chars-minimum!!",
    }
    base.update(overrides)
    return Settings(**base)


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class FakeNotificationRepository:
    def __init__(self) -> None:
        self.items = []

    async def create(self, notification):  # noqa: ANN001
        now = datetime.now(tz=UTC)
        notification.id = notification.id or uuid4()
        notification.public_id = notification.public_id or uuid4()
        notification.created_at = notification.created_at or now
        notification.updated_at = now
        self.items.append(notification)
        return notification

    async def get_by_public_id(self, notification_public_id: UUID):  # noqa: ANN001
        return next((item for item in self.items if item.public_id == notification_public_id), None)

    async def list_all(self):
        return list(self.items)

    async def count_by_status(self):
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item.status] = counts.get(item.status, 0) + 1
        return sorted(counts.items())

    async def count_by_channel(self):
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item.channel] = counts.get(item.channel, 0) + 1
        return sorted(counts.items())


class FakeNotificationDeliveryRepository:
    def __init__(self) -> None:
        self.items = []

    async def create(self, delivery: NotificationDelivery) -> NotificationDelivery:
        now = datetime.now(tz=UTC)
        delivery.id = delivery.id or uuid4()
        delivery.public_id = delivery.public_id or uuid4()
        delivery.created_at = delivery.created_at or now
        delivery.updated_at = now
        if delivery.email_delivery_log_id is not None:
            delivery.email_delivery_log = SimpleNamespace(public_id=uuid4())
        self.items.append(delivery)
        return delivery

    async def list_for_notification(self, notification_id: UUID):
        return [item for item in self.items if item.notification_id == notification_id]


class FakeNotificationEventRepository:
    def __init__(self) -> None:
        self.items = []

    async def append(self, event: NotificationEvent) -> NotificationEvent:
        now = datetime.now(tz=UTC)
        event.id = event.id or uuid4()
        event.public_id = event.public_id or uuid4()
        event.created_at = event.created_at or now
        event.updated_at = now
        self.items.append(event)
        return event

    async def list_for_notification(self, notification_id: UUID):
        return [item for item in self.items if item.notification_id == notification_id]


class FakePreferenceService:
    def __init__(self, decision: NotificationPreferenceDecision) -> None:
        self.decision = decision

    async def evaluate(self, recipient_user_id, event_type, requested_channel):  # noqa: ANN001
        return self.decision


class FakeDispatcher:
    def __init__(self, outcome) -> None:  # noqa: ANN001
        self.outcome = outcome
        self.calls = []

    async def dispatch(self, notification):  # noqa: ANN001
        self.calls.append(notification)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _build_service(*, dispatcher, preference_decision: NotificationPreferenceDecision) -> NotificationService:  # noqa: ANN001
    session = FakeSession()
    service = NotificationService(session, settings=_settings())  # type: ignore[arg-type]
    service._notifications = FakeNotificationRepository()  # type: ignore[assignment]
    service._deliveries = FakeNotificationDeliveryRepository()  # type: ignore[assignment]
    service._events = FakeNotificationEventRepository()  # type: ignore[assignment]
    service._preferences = FakePreferenceService(preference_decision)  # type: ignore[assignment]
    service._dispatcher = dispatcher  # type: ignore[assignment]
    return service


def _trust_invitation_request() -> NotificationRequest:
    return NotificationRequest(
        event_type="trust_invitation_created",
        recipient_email="aman3@test.com",
        payload={
            "organization_name": "Kairo Labs",
            "subject_name": "Aman Jha",
            "invitation_url": "https://api.example.com/api/v1/trust-invitations/token",
            "expires_at_iso": "2026-07-10T12:00:00+00:00",
        },
    )


@pytest.mark.asyncio
async def test_create_and_dispatch_records_sent_notification_delivery() -> None:
    dispatcher = FakeDispatcher(
        NotificationDispatchOutcome(
            status=NotificationStatus.SENT.value,
            provider="console",
            provider_message_id="msg_123",
            dispatched_at=datetime.now(tz=UTC),
            delivered_at=datetime.now(tz=UTC),
        )
    )
    service = _build_service(
        dispatcher=dispatcher,
        preference_decision=NotificationPreferenceDecision(enabled=True, selected_channel="email"),
    )

    detail = await service.create_and_dispatch(_trust_invitation_request(), actor_user_id=uuid4())

    assert detail.status == NotificationStatus.SENT.value
    assert detail.channel == "email"
    assert len(detail.deliveries) == 1
    assert detail.deliveries[0].provider == "console"
    assert [item.event_type for item in detail.history] == [
        "notification_created",
        "notification_dispatch_started",
        "notification_dispatch_completed",
    ]
    assert len(dispatcher.calls) == 1


@pytest.mark.asyncio
async def test_create_and_dispatch_respects_disabled_preferences() -> None:
    dispatcher = FakeDispatcher(
        NotificationDispatchOutcome(
            status=NotificationStatus.SENT.value,
            provider="console",
        )
    )
    service = _build_service(
        dispatcher=dispatcher,
        preference_decision=NotificationPreferenceDecision(enabled=False, selected_channel="email"),
    )

    detail = await service.create_and_dispatch(_trust_invitation_request())

    assert detail.status == NotificationStatus.SKIPPED.value
    assert detail.deliveries == []
    assert len(dispatcher.calls) == 0
    assert [item.event_type for item in detail.history] == [
        "notification_created",
        "notification_skipped",
    ]


@pytest.mark.asyncio
async def test_create_and_dispatch_marks_failed_delivery_when_channel_unavailable() -> None:
    dispatcher = FakeDispatcher(ServiceUnavailableError("email provider unavailable"))
    service = _build_service(
        dispatcher=dispatcher,
        preference_decision=NotificationPreferenceDecision(enabled=True, selected_channel="email"),
    )

    with pytest.raises(ServiceUnavailableError, match="email provider unavailable"):
        await service.create_and_dispatch(_trust_invitation_request())

    notification = service._notifications.items[0]  # type: ignore[attr-defined]
    assert notification.status == NotificationStatus.FAILED.value
    assert notification.failed_at is not None
    history = await service._events.list_for_notification(notification.id)  # type: ignore[attr-defined]
    assert [item.event_type for item in history] == [
        "notification_created",
        "notification_dispatch_started",
        "notification_dispatch_failed",
    ]


@pytest.mark.asyncio
async def test_resend_creates_additional_delivery_history() -> None:
    dispatcher = FakeDispatcher(
        NotificationDispatchOutcome(
            status=NotificationStatus.SENT.value,
            provider="console",
            dispatched_at=datetime.now(tz=UTC),
            delivered_at=datetime.now(tz=UTC),
        )
    )
    service = _build_service(
        dispatcher=dispatcher,
        preference_decision=NotificationPreferenceDecision(enabled=True, selected_channel="email"),
    )

    created = await service.create_and_dispatch(_trust_invitation_request())
    resent = await service.resend(created.public_id, actor_user_id=uuid4())

    assert resent.status == NotificationStatus.SENT.value
    assert len(resent.deliveries) == 2
    assert [item.event_type for item in resent.history][-3:] == [
        "notification_resend_requested",
        "notification_dispatch_started",
        "notification_dispatch_completed",
    ]
