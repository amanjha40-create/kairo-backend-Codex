"""Public website contact-form handling."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.config import Settings, get_settings
from app.schemas.public_contact import PublicContactAcceptedResponse, PublicContactRequest
from app.services.email_delivery_service import EmailDeliveryService

logger = logging.getLogger(__name__)

_CONTACT_TO_EMAIL = "contact@kairoid.com"


class PublicContactService:
    def __init__(
        self,
        email_delivery: EmailDeliveryService,
        settings: Settings | None = None,
    ) -> None:
        self._email_delivery = email_delivery
        self._settings = settings or get_settings()

    async def submit(
        self,
        payload: PublicContactRequest,
        *,
        request_id: str,
        client_host: str | None,
    ) -> PublicContactAcceptedResponse:
        if payload.website:
            logger.warning(
                "public_contact_honeypot_rejected",
                extra={
                    "event": "public_contact_honeypot_rejected",
                    "client_host_present": bool(client_host),
                    "work_email_domain": payload.work_email.split("@")[-1],
                },
            )
            return PublicContactAcceptedResponse()

        logger.info(
            "public_contact_submission_accepted",
            extra={
                "event": "public_contact_submission_accepted",
                "request_id": request_id,
                "company": payload.company,
                "hires_per_month": payload.hires_per_month,
                "work_email_domain": payload.work_email.split("@")[-1],
                "message_length": len(payload.message),
            },
        )
        try:
            log = await self._email_delivery.queue_template_email(
                template_key="contact_form_submission",
                to_email=_CONTACT_TO_EMAIL,
                template_data={
                    "full_name": payload.full_name,
                    "work_email": str(payload.work_email),
                    "company": payload.company,
                    "hires_per_month": payload.hires_per_month,
                    "message": payload.message,
                    "submitted_at_iso": datetime.now(tz=UTC).isoformat(),
                    "request_id": request_id,
                },
                raise_on_dispatch_failure=True,
            )
        except Exception:
            logger.warning(
                "public_contact_email_failed",
                extra={
                    "event": "public_contact_email_failed",
                    "request_id": request_id,
                    "work_email_domain": payload.work_email.split("@")[-1],
                },
            )
            raise
        logger.info(
            "public_contact_email_accepted",
            extra={
                "event": "public_contact_email_accepted",
                "request_id": request_id,
                "provider": log.provider,
                "email_delivery_log_public_id": str(log.public_id),
                "status": log.status,
            },
        )
        return PublicContactAcceptedResponse()
