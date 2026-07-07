"""Unit tests for job dispatching."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from app.config import Settings
from app.schemas.email_delivery import EmailSendJobPayload, RenderedEmailMessage
from app.services.job_dispatcher import JobDispatcher
from app.workers.registry import registered_types


def _settings(**overrides: object) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        "jwt_secret_key": "test-jwt-secret-key-32-chars-minimum!!",
    }
    base.update(overrides)
    return Settings(**base)


def test_job_dispatcher_import_registers_email_handler() -> None:
    assert "email.send" in registered_types()


class FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


@pytest.mark.asyncio
async def test_inline_dispatch_executes_registered_handler() -> None:
    session = FakeSession()
    received: dict[str, object] = {}

    @asynccontextmanager
    async def fake_session_factory():
        yield session

    async def fake_handler(data, db_session):  # noqa: ANN001
        received["data"] = data
        received["session"] = db_session

    dispatcher = JobDispatcher(
        _settings(job_backend="inline"),
        session_factory=fake_session_factory,
        handler_resolver=lambda message_type: fake_handler if message_type == "email.send" else None,
    )

    await dispatcher.dispatch_email(
        EmailSendJobPayload(
            email_delivery_log_public_id="00000000-0000-0000-0000-000000000001",
            message=RenderedEmailMessage(
                template_key="trust_invitation",
                template_version="v1",
                to_email="aman3@test.com",
                subject="Example",
                text_body="body",
            ),
        )
    )

    assert received["session"] is session
    assert session.committed is True
    assert session.rolled_back is False


@pytest.mark.asyncio
async def test_sqs_dispatch_uses_publisher() -> None:
    published: list[tuple[str, dict[str, object]]] = []

    async def fake_publisher(envelope):  # noqa: ANN001
        published.append((envelope.type, envelope.data))
        return "message-id"

    dispatcher = JobDispatcher(
        _settings(job_backend="sqs"),
        publisher=fake_publisher,
    )

    await dispatcher.dispatch_email(
        EmailSendJobPayload(
            email_delivery_log_public_id="00000000-0000-0000-0000-000000000001",
            message=RenderedEmailMessage(
                template_key="trust_invitation",
                template_version="v1",
                to_email="aman3@test.com",
                subject="Example",
                text_body="body",
            ),
        )
    )

    assert published[0][0] == "email.send"
