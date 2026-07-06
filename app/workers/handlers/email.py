"""Email delivery worker handler."""

from __future__ import annotations

from datetime import UTC, datetime
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.integrations.email.providers import get_email_provider
from app.repositories.email_delivery_log import EmailDeliveryLogRepository
from app.schemas.email_delivery import EmailSendJobPayload
from app.workers.registry import register_handler

logger = logging.getLogger(__name__)


class EmailSendJobHandler:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        *,
        logs: EmailDeliveryLogRepository | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._logs = logs or EmailDeliveryLogRepository(session)

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


@register_handler("email.send")
async def handle_email_send_job(data: dict[str, object], session: AsyncSession) -> None:
    await EmailSendJobHandler(session).handle(data)
