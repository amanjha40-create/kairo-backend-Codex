"""Unit tests for email delivery orchestration."""

from __future__ import annotations

from uuid import uuid4
from uuid import UUID

import pytest

from app.config import Settings
from app.models.email_delivery_log import EmailDeliveryLog
from app.services.email_delivery_service import EmailDeliveryService


def _settings(**overrides: object) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        "jwt_secret_key": "test-jwt-secret-key-32-chars-minimum!!",
    }
    base.update(overrides)
    return Settings(**base)


class FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, obj) -> None:  # noqa: ANN001
        return None


class FakeEmailDeliveryLogRepository:
    def __init__(self) -> None:
        self.created: EmailDeliveryLog | None = None

    async def create(self, log: EmailDeliveryLog) -> EmailDeliveryLog:
        if log.public_id is None:
            log.public_id = uuid4()
        self.created = log
        return log


class FakeJobDispatcher:
    def __init__(self) -> None:
        self.payload = None

    async def dispatch_email(self, payload) -> None:  # noqa: ANN001
        self.payload = payload


@pytest.mark.asyncio
async def test_queue_template_email_creates_audit_log_and_dispatches() -> None:
    session = FakeSession()
    logs = FakeEmailDeliveryLogRepository()
    dispatcher = FakeJobDispatcher()
    service = EmailDeliveryService(
        session,  # type: ignore[arg-type]
        _settings(email_backend="console", email_send_enabled=False),
        dispatcher=dispatcher,  # type: ignore[arg-type]
        logs=logs,  # type: ignore[arg-type]
    )

    result = await service.queue_template_email(
        template_key="trust_invitation",
        to_email="aman3@test.com",
        template_data={
            "organization_name": "Kairo Labs",
            "subject_name": "Aman Jha",
            "invitation_url": "https://example.com/invite/token",
            "expires_at_iso": "2026-07-10T12:00:00+00:00",
        },
        recipient_user_id=UUID("00000000-0000-0000-0000-000000000111"),
    )

    assert session.committed is True
    assert logs.created is result
    assert result.template_key == "trust_invitation"
    assert result.template_version == "v1"
    assert result.status == "queued"
    assert result.provider == "console"
    assert "invitation_url" not in result.payload
    assert dispatcher.payload is not None
