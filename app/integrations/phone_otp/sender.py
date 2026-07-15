"""Phone OTP delivery adapters."""

from __future__ import annotations

import hmac
import logging
from typing import Protocol

from app.auth.phone_utils import mask_phone
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class PhoneOtpSender(Protocol):
    def challenge_code(self, *, to_phone: str, generated_code: str) -> str: ...

    async def send_signup_otp(self, *, to_phone: str, code: str, ttl_minutes: int) -> None: ...


class ConsolePhoneOtpSender:
    """Safe local-development provider that never contacts a real SMS gateway."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def challenge_code(self, *, to_phone: str, generated_code: str) -> str:
        del to_phone
        return generated_code

    async def send_signup_otp(self, *, to_phone: str, code: str, ttl_minutes: int) -> None:
        extra: dict[str, object] = {
            "event": "signup_phone_otp",
            "to_phone_masked": f"{to_phone[:4]}***{to_phone[-2:]}" if len(to_phone) > 6 else "***",
            "ttl_minutes": ttl_minutes,
        }
        if not self._settings.is_production:
            extra["otp_code"] = code
        logger.info("signup_phone_otp", extra=extra)


class StagingFixedPhoneOtpSender:
    """Staging-only fixed challenge provider restricted to approved E.164 numbers."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def _is_allowed(self, to_phone: str) -> bool:
        return any(
            hmac.compare_digest(to_phone, allowed)
            for allowed in self._settings.staging_phone_otp_allowed_numbers
        )

    def challenge_code(self, *, to_phone: str, generated_code: str) -> str:
        if not self._is_allowed(to_phone) or self._settings.staging_phone_otp_code is None:
            return generated_code
        return self._settings.staging_phone_otp_code.get_secret_value()

    async def send_signup_otp(self, *, to_phone: str, code: str, ttl_minutes: int) -> None:
        del code
        logger.info(
            "staging_phone_otp_challenge_created",
            extra={
                "event": "staging_phone_otp_challenge_created",
                "to_phone_masked": mask_phone(to_phone),
                "ttl_minutes": ttl_minutes,
            },
        )


def get_phone_otp_sender(settings: Settings | None = None) -> PhoneOtpSender:
    s = settings or get_settings()
    backend = s.phone_otp_backend.lower().strip()
    if backend == "console":
        return ConsolePhoneOtpSender(s)
    if backend == "staging_fixed":
        return StagingFixedPhoneOtpSender(s)
    logger.warning("unknown_phone_otp_backend", extra={"phone_otp_backend": backend})
    return ConsolePhoneOtpSender(s)
