"""Phone OTP delivery adapters."""

from __future__ import annotations

import logging
from typing import Protocol

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class PhoneOtpSender(Protocol):
    async def send_signup_otp(self, *, to_phone: str, code: str, ttl_minutes: int) -> None: ...


class ConsolePhoneOtpSender:
    """Safe local-development provider that never contacts a real SMS gateway."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def send_signup_otp(self, *, to_phone: str, code: str, ttl_minutes: int) -> None:
        extra: dict[str, object] = {
            "event": "signup_phone_otp",
            "to_phone_masked": f"{to_phone[:4]}***{to_phone[-2:]}" if len(to_phone) > 6 else "***",
            "ttl_minutes": ttl_minutes,
        }
        if not self._settings.is_production:
            extra["otp_code"] = code
        logger.info("signup_phone_otp", extra=extra)


def get_phone_otp_sender(settings: Settings | None = None) -> PhoneOtpSender:
    s = settings or get_settings()
    backend = s.phone_otp_backend.lower().strip()
    if backend == "console":
        return ConsolePhoneOtpSender(s)
    logger.warning("unknown_phone_otp_backend", extra={"phone_otp_backend": backend})
    return ConsolePhoneOtpSender(s)
