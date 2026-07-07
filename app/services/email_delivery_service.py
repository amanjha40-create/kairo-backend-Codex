"""High-level orchestration for transactional email delivery."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.integrations.email.providers import get_email_provider
from app.integrations.email.renderer import EmailTemplateRenderer
from app.models.email_delivery_log import EmailDeliveryLog
from app.repositories.email_delivery_log import EmailDeliveryLogRepository
from app.schemas.email_delivery import EmailSendJobPayload
from app.services.job_dispatcher import JobDispatcher

logger = logging.getLogger(__name__)


class EmailDeliveryService:
    """Render, audit, and dispatch email jobs without coupling services to providers."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        *,
        renderer: EmailTemplateRenderer | None = None,
        dispatcher: JobDispatcher | None = None,
        logs: EmailDeliveryLogRepository | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._renderer = renderer or EmailTemplateRenderer()
        self._dispatcher = dispatcher or JobDispatcher(self._settings)
        self._logs = logs or EmailDeliveryLogRepository(session)

    async def queue_template_email(
        self,
        *,
        template_key: str,
        to_email: str,
        template_data: dict[str, object],
        recipient_user_id: UUID | None = None,
    ) -> EmailDeliveryLog:
        rendered = self._renderer.render(
            template_key=template_key,
            to_email=to_email,
            data=template_data,
        )
        provider = get_email_provider(self._settings)
        log = EmailDeliveryLog(
            template_key=rendered.template_key,
            template_version=rendered.template_version,
            recipient_email=rendered.to_email,
            recipient_user_id=recipient_user_id,
            provider=getattr(provider, "provider_name", self._settings.email_backend),
            status="queued",
            subject=rendered.subject,
            payload=rendered.audit_payload,
        )
        await self._logs.create(log)
        await self._session.commit()

        try:
            await self._dispatcher.dispatch_email(
                EmailSendJobPayload(
                    email_delivery_log_public_id=log.public_id,
                    message=rendered,
                )
            )
        except Exception as exc:
            logger.warning(
                "email_dispatch_failed",
                extra={
                    "event": "email_dispatch_failed",
                    "template_key": rendered.template_key,
                    "template_version": rendered.template_version,
                    "error_type": type(exc).__name__,
                },
            )

        await self._session.refresh(log)
        return log
