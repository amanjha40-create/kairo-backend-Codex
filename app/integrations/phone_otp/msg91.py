"""Server-side MSG91 OTP provider."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.auth.phone_utils import mask_phone
from app.config import Settings, get_settings
from app.exceptions import (
    RateLimitError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationAppError,
)

logger = logging.getLogger(__name__)

_INVALID_PHONE_HINTS = (
    "invalid mobile",
    "invalid phone",
    "mobile number is invalid",
    "mobile no. is invalid",
)
_RATE_LIMIT_HINTS = (
    "too many",
    "try again later",
    "please wait",
    "otp already sent",
    "limit exceeded",
    "throttle",
)
_INVALID_OTP_HINTS = (
    "invalid otp",
    "incorrect otp",
    "wrong otp",
    "otp not matched",
    "otp does not match",
)
_EXPIRED_OTP_HINTS = (
    "expired",
    "timeout",
)
_RETRY_EXHAUSTED_HINTS = (
    "retry exhausted",
    "retry limit",
    "maximum retry",
)


@dataclass(slots=True)
class Msg91DispatchResult:
    provider: str
    request_id: str


def _sanitize_msg91_error(response: httpx.Response) -> dict[str, str | int]:
    error_code = f"http_{response.status_code}"
    error_message = response.text[:300]
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        error_code = str(payload.get("type") or payload.get("code") or error_code)
        error_message = str(payload.get("message") or error_message)[:300]
    return {
        "http_status": response.status_code,
        "provider_error_code": error_code,
        "provider_error_message": error_message,
    }


def _extract_request_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("request_id", "requestId", "reqId"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    message = payload.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    return None


def _contains_hint(text: str, hints: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in hints)


def _raise_send_or_retry_error(sanitized: dict[str, str | int]) -> None:
    detail = (
        f"{sanitized.get('provider_error_code', '')} "
        f"{sanitized.get('provider_error_message', '')}"
    )
    if (
        _contains_hint(detail, _INVALID_PHONE_HINTS)
        or str(sanitized.get("provider_error_code")) == "202"
    ):
        raise ValidationAppError("Phone number must be a valid E.164 number")
    if _contains_hint(detail, _RETRY_EXHAUSTED_HINTS):
        raise RateLimitError("Retry limit reached. Request a new verification code later.")
    if _contains_hint(detail, _RATE_LIMIT_HINTS):
        raise RateLimitError("Too many verification codes sent. Try again later.")
    raise ServiceUnavailableError("Phone verification is temporarily unavailable")


def _raise_verify_error(sanitized: dict[str, str | int]) -> None:
    detail = (
        f"{sanitized.get('provider_error_code', '')} "
        f"{sanitized.get('provider_error_message', '')}"
    )
    if _contains_hint(detail, _INVALID_OTP_HINTS) or _contains_hint(detail, _EXPIRED_OTP_HINTS):
        raise UnauthorizedError("Invalid or expired verification code")
    if _contains_hint(detail, _RATE_LIMIT_HINTS):
        raise RateLimitError("Too many verification attempts. Try again later.")
    raise ServiceUnavailableError("Phone verification is temporarily unavailable")


class Msg91PhoneOtpProvider:
    provider_name = "msg91"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client

    async def send_signup_otp(self, *, to_phone: str) -> Msg91DispatchResult:
        payload = await self._request(
            "POST",
            "/otp",
            params={
                "authkey": self._auth_key(),
                "mobile": self._provider_identifier(to_phone),
                "template_id": self._settings.msg91_template_id or "",
                "otp_expiry": str(self._settings.msg91_otp_expiry_minutes),
            },
            log_event="otp_provider_accepted",
            log_phone=to_phone,
            action="send",
        )
        request_id = _extract_request_id(payload)
        if not request_id:
            logger.warning(
                "msg91_send_missing_request_id",
                extra={
                    "event": "msg91_send_missing_request_id",
                    "provider": self.provider_name,
                    "response_keys": (
                        sorted(payload.keys())[:10]
                        if isinstance(payload, dict)
                        else []
                    ),
                },
            )
            raise ServiceUnavailableError("Phone verification is temporarily unavailable")
        return Msg91DispatchResult(provider=self.provider_name, request_id=request_id)

    async def resend_signup_otp(
        self,
        *,
        to_phone: str,
        prior_request_id: str | None,
    ) -> Msg91DispatchResult:
        payload = await self._request(
            "GET",
            "/otp/retry",
            params={
                "authkey": self._auth_key(),
                "mobile": self._provider_identifier(to_phone),
                "retrytype": self._settings.msg91_retry_type,
            },
            log_event="otp_provider_accepted",
            log_phone=to_phone,
            action="resend",
        )
        request_id = _extract_request_id(payload) or prior_request_id
        if not request_id:
            logger.warning(
                "msg91_resend_missing_request_id",
                extra={
                    "event": "msg91_resend_missing_request_id",
                    "provider": self.provider_name,
                    "response_keys": (
                        sorted(payload.keys())[:10]
                        if isinstance(payload, dict)
                        else []
                    ),
                },
            )
            raise ServiceUnavailableError("Phone verification is temporarily unavailable")
        return Msg91DispatchResult(provider=self.provider_name, request_id=request_id)

    async def verify_signup_otp(self, *, to_phone: str, code: str) -> None:
        await self._request(
            "GET",
            "/otp/verify",
            params={
                "authkey": self._auth_key(),
                "mobile": self._provider_identifier(to_phone),
                "otp": code,
            },
            log_event="otp_verify_success",
            log_phone=to_phone,
            action="verify",
        )

    def _auth_key(self) -> str:
        auth_key = (
            self._settings.msg91_auth_key.get_secret_value()
            if self._settings.msg91_auth_key
            else ""
        )
        if not auth_key:
            raise ServiceUnavailableError("Phone verification is not configured")
        return auth_key

    def _provider_identifier(self, to_phone: str) -> str:
        return to_phone.lstrip("+")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str],
        log_event: str,
        log_phone: str,
        action: str,
    ) -> Any:
        created_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._settings.msg91_timeout_seconds)
        try:
            response = await client.request(
                method,
                f"{self._settings.msg91_base_url.rstrip('/')}{path}",
                params=params,
                headers={"accept": "application/json"},
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            logger.warning(
                "msg91_transport_timeout",
                extra={
                    "event": "msg91_transport_timeout",
                    "provider": self.provider_name,
                    "action": action,
                    "to_phone_masked": mask_phone(log_phone),
                    "error_type": type(exc).__name__,
                },
            )
            raise ServiceUnavailableError("Phone verification is temporarily unavailable") from exc
        except httpx.HTTPStatusError as exc:
            sanitized = _sanitize_msg91_error(exc.response)
            log_message = (
                "msg91_request_rejected"
                if 400 <= exc.response.status_code < 500
                else "msg91_request_failed"
            )
            logger.info(
                log_message,
                extra={
                    "event": log_message,
                    "provider": self.provider_name,
                    "action": action,
                    "to_phone_masked": mask_phone(log_phone),
                    **sanitized,
                },
            )
            if action == "verify":
                _raise_verify_error(sanitized)
            _raise_send_or_retry_error(sanitized)
        except httpx.HTTPError as exc:
            logger.warning(
                "msg91_transport_failed",
                extra={
                    "event": "msg91_transport_failed",
                    "provider": self.provider_name,
                    "action": action,
                    "to_phone_masked": mask_phone(log_phone),
                    "error_type": type(exc).__name__,
                },
            )
            raise ServiceUnavailableError("Phone verification is temporarily unavailable") from exc
        finally:
            if created_client:
                await client.aclose()

        try:
            payload = response.json()
        except ValueError as exc:
            logger.warning(
                "msg91_invalid_response",
                extra={
                    "event": "msg91_invalid_response",
                    "provider": self.provider_name,
                    "action": action,
                    "to_phone_masked": mask_phone(log_phone),
                    "http_status": response.status_code,
                },
            )
            raise ServiceUnavailableError("Phone verification is temporarily unavailable") from exc

        logger.info(
            log_event,
            extra={
                "event": log_event,
                "provider": self.provider_name,
                "action": action,
                "to_phone_masked": mask_phone(log_phone),
                "request_id_present": _extract_request_id(payload) is not None,
                "template_id_configured": bool(self._settings.msg91_template_id),
                "sender_id_configured": bool(self._settings.msg91_sender_id),
            },
        )
        return payload
