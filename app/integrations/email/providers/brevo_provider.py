"""Brevo transactional email provider."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.exceptions import ServiceUnavailableError
from app.schemas.email_delivery import EmailSendResult, RenderedEmailMessage

logger = logging.getLogger(__name__)


def _sanitize_brevo_error(response: httpx.Response) -> dict[str, str | int]:
    error_code = f"http_{response.status_code}"
    error_message = response.text[:300]
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        error_code = str(payload.get("code") or error_code)
        error_message = str(payload.get("message") or error_message)[:300]
    return {
        "http_status": response.status_code,
        "provider_error_code": error_code,
        "provider_error_message": error_message,
    }


class BrevoEmailProvider:
    provider_name = "brevo"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client

    async def send(self, message: RenderedEmailMessage) -> EmailSendResult:
        if not self._settings.email_send_enabled:
            logger.info(
                "email_delivery_brevo_skipped",
                extra={
                    "event": "email_delivery_brevo_skipped",
                    "template_key": message.template_key,
                    "template_version": message.template_version,
                },
            )
            return EmailSendResult(provider=self.provider_name, status="skipped")

        api_key = (
            self._settings.brevo_api_key.get_secret_value()
            if self._settings.brevo_api_key
            else None
        )
        if not api_key:
            raise ServiceUnavailableError("Email is not configured")

        payload: dict[str, object] = {
            "sender": {
                "email": message.from_email or self._settings.email_from,
                "name": self._settings.email_from_name,
            },
            "to": [{"email": message.to_email}],
            "subject": message.subject,
            "textContent": message.text_body,
            "headers": {
                "X-Kairo-Template-Key": message.template_key,
                "X-Kairo-Template-Version": message.template_version,
            },
        }
        if message.html_body:
            payload["htmlContent"] = message.html_body
        reply_to = message.reply_to or self._settings.email_reply_to
        if reply_to:
            payload["replyTo"] = {"email": reply_to}
        if message.tags:
            payload["tags"] = message.tags
        if message.correlation_id:
            headers = payload["headers"]
            assert isinstance(headers, dict)
            headers["X-Kairo-Correlation-Id"] = message.correlation_id

        created_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._settings.brevo_timeout_seconds)
        try:
            response = await client.post(
                f"{self._settings.brevo_api_base_url.rstrip('/')}/smtp/email",
                headers={
                    "accept": "application/json",
                    "api-key": api_key,
                    "content-type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            logger.warning(
                "brevo_send_timeout",
                extra={
                    "event": "brevo_send_timeout",
                    "template_key": message.template_key,
                    "template_version": message.template_version,
                    "error_type": type(exc).__name__,
                },
            )
            raise ServiceUnavailableError("Unable to send email") from exc
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "brevo_send_failed",
                extra={
                    "event": "brevo_send_failed",
                    "template_key": message.template_key,
                    "template_version": message.template_version,
                    **_sanitize_brevo_error(exc.response),
                },
            )
            raise ServiceUnavailableError("Unable to send email") from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "brevo_transport_failed",
                extra={
                    "event": "brevo_transport_failed",
                    "template_key": message.template_key,
                    "template_version": message.template_version,
                    "error_type": type(exc).__name__,
                },
            )
            raise ServiceUnavailableError("Unable to send email") from exc
        finally:
            if created_client:
                await client.aclose()

        data: dict[str, Any]
        try:
            data = response.json()
        except ValueError:
            data = {}
        return EmailSendResult(
            provider=self.provider_name,
            status="sent",
            provider_message_id=str(data.get("messageId") or ""),
        )
