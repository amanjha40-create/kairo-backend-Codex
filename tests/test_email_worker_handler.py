"""Unit tests for email job handling."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.config import Settings
from app.models.email_delivery_log import EmailDeliveryLog
from app.schemas.email_delivery import EmailSendResult
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
