"""Server-side phone OTP verification adapters."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.config import Settings, get_settings
from app.exceptions import ServiceUnavailableError, UnauthorizedError

logger = logging.getLogger(__name__)

MSG91_VERIFY_ACCESS_TOKEN_URL = "https://control.msg91.com/api/v5/widget/verifyAccessToken"
_MSG91_IDENTIFIER_KEYS = {
    "identifier",
    "mobile",
    "msisdn",
    "number",
    "phone",
    "phone_number",
}


@dataclass(slots=True)
class PhoneVerificationResult:
    provider: str
    verified_identifier: str


class PhoneOtpVerifier(Protocol):
    async def verify_signup_access_token(self, *, access_token: str) -> PhoneVerificationResult: ...


class UnsupportedPhoneOtpVerifier:
    async def verify_signup_access_token(self, *, access_token: str) -> PhoneVerificationResult:
        del access_token
        raise UnauthorizedError("Phone verification access token is not supported")


def _sanitize_msg91_error(response: httpx.Response) -> dict[str, str | int]:
    error_code = f"http_{response.status_code}"
    error_message = response.text[:200]
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        error_code = str(payload.get("type") or payload.get("code") or error_code)
        error_message = str(payload.get("message") or error_message)[:200]
    return {
        "http_status": response.status_code,
        "provider_error_code": error_code,
        "provider_error_message": error_message,
    }


def _iter_identifier_values(payload: Any) -> list[str]:
    values: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if (
                isinstance(key, str)
                and key.lower() in _MSG91_IDENTIFIER_KEYS
                and isinstance(value, str)
            ):
                cleaned = value.strip()
                if cleaned:
                    values.append(cleaned)
            values.extend(_iter_identifier_values(value))
    elif isinstance(payload, list):
        for item in payload:
            values.extend(_iter_identifier_values(item))
    return values


class Msg91PhoneOtpVerifier:
    provider_name = "msg91"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client

    async def verify_signup_access_token(self, *, access_token: str) -> PhoneVerificationResult:
        auth_key = (
            self._settings.msg91_auth_key.get_secret_value()
            if self._settings.msg91_auth_key
            else None
        )
        if not auth_key:
            logger.warning(
                "msg91_verify_not_configured",
                extra={"event": "msg91_verify_not_configured"},
            )
            raise ServiceUnavailableError("Phone verification is not configured")

        created_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._settings.msg91_timeout_seconds)
        try:
            response = await client.post(
                MSG91_VERIFY_ACCESS_TOKEN_URL,
                headers={
                    "accept": "application/json",
                    "content-type": "application/json",
                },
                json={
                    "authkey": auth_key,
                    "access-token": access_token,
                },
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            logger.warning(
                "msg91_verify_timeout",
                extra={"event": "msg91_verify_timeout", "error_type": type(exc).__name__},
            )
            raise ServiceUnavailableError("Phone verification service unavailable") from exc
        except httpx.HTTPStatusError as exc:
            sanitized = _sanitize_msg91_error(exc.response)
            if 400 <= exc.response.status_code < 500:
                logger.info(
                    "msg91_verify_rejected",
                    extra={"event": "msg91_verify_rejected", **sanitized},
                )
                raise UnauthorizedError("Invalid or expired phone verification token") from exc
            logger.warning(
                "msg91_verify_failed",
                extra={"event": "msg91_verify_failed", **sanitized},
            )
            raise ServiceUnavailableError("Phone verification service unavailable") from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "msg91_verify_transport_failed",
                extra={"event": "msg91_verify_transport_failed", "error_type": type(exc).__name__},
            )
            raise ServiceUnavailableError("Phone verification service unavailable") from exc
        finally:
            if created_client:
                await client.aclose()

        try:
            payload = response.json()
        except ValueError as exc:
            logger.warning(
                "msg91_verify_invalid_response",
                extra={
                    "event": "msg91_verify_invalid_response",
                    "http_status": response.status_code,
                },
            )
            raise UnauthorizedError("Invalid or expired phone verification token") from exc

        identifiers = _iter_identifier_values(payload)
        if not identifiers:
            logger.warning(
                "msg91_verify_missing_identifier",
                extra={
                    "event": "msg91_verify_missing_identifier",
                    "http_status": response.status_code,
                    "response_keys": (
                        sorted(payload.keys())[:10] if isinstance(payload, dict) else []
                    ),
                },
            )
            raise UnauthorizedError("Invalid or expired phone verification token")

        return PhoneVerificationResult(
            provider=self.provider_name,
            verified_identifier=identifiers[0],
        )


def get_phone_otp_verifier(settings: Settings | None = None) -> PhoneOtpVerifier:
    s = settings or get_settings()
    if s.phone_otp_backend.lower().strip() == "msg91":
        return Msg91PhoneOtpVerifier(s)
    return UnsupportedPhoneOtpVerifier()
