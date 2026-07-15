"""Async job dispatch abstraction."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import async_session_factory
from app.infrastructure.sqs import SqsJobEnvelope, send_json_message
from app.schemas.email_delivery import EmailSendJobPayload
from app.workers.registry import HandlerFn, get_handler

import app.workers.handlers  # noqa: F401 - ensure handler registration for inline dispatch


AsyncSessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
PublisherFn = Callable[[SqsJobEnvelope], Awaitable[str]]
HandlerResolver = Callable[[str], HandlerFn | None]


class JobDispatcher:
    """Dispatch inline in development, or publish envelopes for worker execution."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        session_factory: AsyncSessionFactory = async_session_factory,
        publisher: PublisherFn = send_json_message,
        handler_resolver: HandlerResolver = get_handler,
    ) -> None:
        self._settings = settings or get_settings()
        self._session_factory = session_factory
        self._publisher = publisher
        self._handler_resolver = handler_resolver

    async def dispatch_email(self, payload: EmailSendJobPayload) -> None:
        if self._settings.job_backend == "sqs":
            await self._publisher(
                SqsJobEnvelope(type="email.send", data=payload.model_dump(mode="json")),
            )
            return

        handler = self._handler_resolver("email.send")
        if handler is None:
            msg = "No handler registered for email.send"
            raise ValueError(msg)

        async with self._session_factory() as session:
            try:
                await handler(payload.model_dump(mode="json"), session)
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def dispatch_resume_processing(self, *, resume_id: str, job_id: str) -> None:
        payload = {"resume_id": resume_id, "job_id": job_id}
        if self._settings.job_backend == "sqs":
            await self._publisher(SqsJobEnvelope(type="resume.process", data=payload))
            return
        handler = self._handler_resolver("resume.process")
        if handler is None:
            raise ValueError("No handler registered for resume.process")
        async with self._session_factory() as session:
            try:
                await handler(payload, session)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
