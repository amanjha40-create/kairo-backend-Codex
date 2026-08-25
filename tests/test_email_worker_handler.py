"""Unit tests for email job handling."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.config import Settings
from app.models.email_delivery_log import EmailDeliveryLog
from app.notifications.enums import NotificationStatus
from app.schemas.email_delivery import EmailSendResult
from app.trust_invitations.enums import TrustInvitationDeliveryState
from app.workers.handlers.email import EmailSendJobHandler


def _settings(**overrides: object) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        "jwt_secret_key": "test-jwt-secret-key-32-chars-minimum!!",
    }
    base.update(overrides)
    return Settings(**base)


class FakeEmailDeliveryLogRepository:
    def __init__(self, log: EmailDeliveryLog | None) -> None:
        self.log = log

    async def get_by_public_id(self, public_id):  # noqa: ANN001
        if self.log is None or self.log.public_id != public_id:
            return None
        return self.log


class FakeProvider:
    provider_name = "console"

    def __init__(self, *, status: str = "sent") -> None:
        self._status = status

    async def send(self, message):  # noqa: ANN001
        return EmailSendResult(provider=self.provider_name, status=self._status)


class FakeNotificationDeliveryRepository:
    def __init__(self, delivery) -> None:  # noqa: ANN001
        self.delivery = delivery

    async def get_by_email_delivery_log_id(self, email_delivery_log_id):  # noqa: ANN001
        if self.delivery is None or self.delivery.email_delivery_log_id != email_delivery_log_id:
            return None
        return self.delivery


class FakeNotificationEventRepository:
    def __init__(self) -> None:
        self.events = []

    async def append(self, event):  # noqa: ANN001
        self.events.append(event)
        return event


class FakeTrustInvitationRepository:
    def __init__(self, invitation) -> None:  # noqa: ANN001
        self.invitation = invitation
        self.events = []

    async def get_by_public_id(self, public_id):  # noqa: ANN001
        if self.invitation is None or self.invitation.public_id != public_id:
            return None
        return self.invitation

    async def add_event(self, event):  # noqa: ANN001
        self.events.append(event)
        return event


@pytest.mark.asyncio
async def test_email_handler_marks_sent() -> None:
    log = EmailDeliveryLog(
        public_id=uuid4(),
        template_key="trust_invitation",
        template_version="v1",
        recipient_email="aman3@test.com",
        provider="console",
        status="queued",
        payload={},
        subject="Invitation",
        queued_at=datetime.now(tz=UTC),
    )
    handler = EmailSendJobHandler(
        session=None,  # type: ignore[arg-type]
        settings=_settings(),
        logs=FakeEmailDeliveryLogRepository(log),  # type: ignore[arg-type]
    )
    handler_module = __import__("app.workers.handlers.email", fromlist=["get_email_provider"])
    original = handler_module.get_email_provider
    handler_module.get_email_provider = lambda settings: FakeProvider(status="sent")
    try:
        await handler.handle(
            {
                "email_delivery_log_public_id": str(log.public_id),
                "message": {
                    "template_key": "trust_invitation",
                    "template_version": "v1",
                    "to_email": "aman3@test.com",
                    "subject": "Invitation",
                    "text_body": "body",
                    "audit_payload": {},
                },
            }
        )
    finally:
        handler_module.get_email_provider = original

    assert log.status == "sent"
    assert log.attempt_count == 1
    assert log.sent_at is not None


@pytest.mark.asyncio
async def test_email_handler_marks_failed_when_provider_raises() -> None:
    log = EmailDeliveryLog(
        public_id=uuid4(),
        template_key="trust_invitation",
        template_version="v1",
        recipient_email="aman3@test.com",
        provider="smtp",
        status="queued",
        payload={},
        subject="Invitation",
        queued_at=datetime.now(tz=UTC),
    )

    class FailingProvider:
        provider_name = "smtp"

        async def send(self, message):  # noqa: ANN001
            raise RuntimeError("smtp down")

    handler = EmailSendJobHandler(
        session=None,  # type: ignore[arg-type]
        settings=_settings(),
        logs=FakeEmailDeliveryLogRepository(log),  # type: ignore[arg-type]
    )
    handler_module = __import__("app.workers.handlers.email", fromlist=["get_email_provider"])
    original = handler_module.get_email_provider
    handler_module.get_email_provider = lambda settings: FailingProvider()
    try:
        await handler.handle(
            {
                "email_delivery_log_public_id": str(log.public_id),
                "message": {
                    "template_key": "trust_invitation",
                    "template_version": "v1",
                    "to_email": "aman3@test.com",
                    "subject": "Invitation",
                    "text_body": "body",
                    "audit_payload": {},
                },
            }
        )
    finally:
        handler_module.get_email_provider = original

    assert log.status == "failed"
    assert log.attempt_count == 1
    assert log.failed_at is not None
    assert log.error_code == "RuntimeError"


@pytest.mark.asyncio
async def test_email_handler_reconciles_notification_and_invitation_on_send() -> None:
    log = EmailDeliveryLog(
        public_id=uuid4(),
        template_key="trust_invitation",
        template_version="v1",
        recipient_email="aman3@test.com",
        provider="brevo",
        status="queued",
        payload={},
        subject="Invitation",
        queued_at=datetime.now(tz=UTC),
    )
    log.id = uuid4()
    invitation = type(
        "Invitation",
        (),
        {
            "id": uuid4(),
            "public_id": uuid4(),
            "delivery_state": TrustInvitationDeliveryState.QUEUED,
            "sent_at": None,
        },
    )()
    notification = type(
        "Notification",
        (),
        {
            "id": uuid4(),
            "status": NotificationStatus.QUEUED.value,
            "sent_at": None,
            "failed_at": None,
            "metadata_payload": {
                "trust_invitation_public_id": str(invitation.public_id),
                "delivery_trigger": "resent",
            },
        },
    )()
    delivery = type(
        "Delivery",
        (),
        {
            "email_delivery_log_id": log.id,
            "channel": "email",
            "status": "queued",
            "provider": None,
            "provider_message_id": None,
            "attempt_count": 0,
            "error_code": None,
            "error_message": None,
            "dispatched_at": None,
            "delivered_at": None,
            "failed_at": None,
            "notification": notification,
        },
    )()
    notification_events = FakeNotificationEventRepository()
    invitations = FakeTrustInvitationRepository(invitation)
    handler = EmailSendJobHandler(
        session=object(),  # type: ignore[arg-type]
        settings=_settings(),
        logs=FakeEmailDeliveryLogRepository(log),  # type: ignore[arg-type]
        deliveries=FakeNotificationDeliveryRepository(delivery),  # type: ignore[arg-type]
        notification_events=notification_events,  # type: ignore[arg-type]
        invitations=invitations,  # type: ignore[arg-type]
    )
    handler_module = __import__("app.workers.handlers.email", fromlist=["get_email_provider"])
    original = handler_module.get_email_provider
    handler_module.get_email_provider = lambda settings: FakeProvider(status="sent")
    try:
        await handler.handle(
            {
                "email_delivery_log_public_id": str(log.public_id),
                "message": {
                    "template_key": "trust_invitation",
                    "template_version": "v1",
                    "to_email": "aman3@test.com",
                    "subject": "Invitation",
                    "text_body": "body",
                    "audit_payload": {},
                },
            }
        )
    finally:
        handler_module.get_email_provider = original

    assert log.status == "sent"
    assert delivery.status == "sent"
    assert notification.status == "sent"
    assert invitation.delivery_state == TrustInvitationDeliveryState.DELIVERED
    assert invitation.sent_at is not None
    assert [event.event_type for event in notification_events.events] == [
        "notification_dispatch_completed",
    ]
    assert [event.event_type for event in invitations.events] == ["resent"]


@pytest.mark.asyncio
async def test_email_handler_reconciles_notification_and_invitation_on_failure() -> None:
    log = EmailDeliveryLog(
        public_id=uuid4(),
        template_key="trust_invitation",
        template_version="v1",
        recipient_email="aman3@test.com",
        provider="brevo",
        status="queued",
        payload={},
        subject="Invitation",
        queued_at=datetime.now(tz=UTC),
    )
    log.id = uuid4()
    invitation = type(
        "Invitation",
        (),
        {
            "id": uuid4(),
            "public_id": uuid4(),
            "delivery_state": TrustInvitationDeliveryState.QUEUED,
            "sent_at": None,
        },
    )()
    notification = type(
        "Notification",
        (),
        {
            "id": uuid4(),
            "status": NotificationStatus.QUEUED.value,
            "sent_at": None,
            "failed_at": None,
            "metadata_payload": {
                "trust_invitation_public_id": str(invitation.public_id),
                "delivery_trigger": "sent",
            },
        },
    )()
    delivery = type(
        "Delivery",
        (),
        {
            "email_delivery_log_id": log.id,
            "channel": "email",
            "status": "queued",
            "provider": None,
            "provider_message_id": None,
            "attempt_count": 0,
            "error_code": None,
            "error_message": None,
            "dispatched_at": None,
            "delivered_at": None,
            "failed_at": None,
            "notification": notification,
        },
    )()
    notification_events = FakeNotificationEventRepository()
    invitations = FakeTrustInvitationRepository(invitation)
    handler = EmailSendJobHandler(
        session=object(),  # type: ignore[arg-type]
        settings=_settings(),
        logs=FakeEmailDeliveryLogRepository(log),  # type: ignore[arg-type]
        deliveries=FakeNotificationDeliveryRepository(delivery),  # type: ignore[arg-type]
        notification_events=notification_events,  # type: ignore[arg-type]
        invitations=invitations,  # type: ignore[arg-type]
    )

    class FailingProvider:
        provider_name = "brevo"

        async def send(self, message):  # noqa: ANN001
            raise RuntimeError("provider down")

    handler_module = __import__("app.workers.handlers.email", fromlist=["get_email_provider"])
    original = handler_module.get_email_provider
    handler_module.get_email_provider = lambda settings: FailingProvider()
    try:
        await handler.handle(
            {
                "email_delivery_log_public_id": str(log.public_id),
                "message": {
                    "template_key": "trust_invitation",
                    "template_version": "v1",
                    "to_email": "aman3@test.com",
                    "subject": "Invitation",
                    "text_body": "body",
                    "audit_payload": {},
                },
            }
        )
    finally:
        handler_module.get_email_provider = original

    assert log.status == "failed"
    assert delivery.status == "failed"
    assert notification.status == "failed"
    assert notification.failed_at is not None
    assert invitation.delivery_state == TrustInvitationDeliveryState.FAILED
    assert [event.event_type for event in notification_events.events] == [
        "notification_dispatch_failed",
    ]
    assert [event.event_type for event in invitations.events] == ["delivery_failed"]
