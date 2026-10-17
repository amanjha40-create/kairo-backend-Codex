"""Existing-account recovery using the canonical signup OTP store/adapters."""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.phone_utils import normalize_phone
from app.auth.signup_otp import SignupOtpStore, generate_otp_code
from app.config import Settings
from app.exceptions import ForbiddenError, ServiceUnavailableError, UnauthorizedError
from app.integrations.phone_otp.msg91 import Msg91PhoneOtpProvider
from app.integrations.phone_otp.sender import PhoneOtpSender
from app.models.user import User
from app.schemas.auth import MobileVerificationResponse
from app.services.private_owner_guard import lock_private_owner

logger = logging.getLogger(__name__)


class MobileVerificationService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        redis: Redis,
        phone: PhoneOtpSender | None,
        msg91: Msg91PhoneOtpProvider | None,
    ) -> None:
        self.session, self.settings = session, settings
        self.otp = SignupOtpStore(redis, settings, scope="existing_mobile")
        self.phone, self.msg91 = phone, msg91

    async def _owner(self, user_id: UUID) -> User:
        user = await lock_private_owner(self.session, user_id)
        if user.role != "user" or user.email_verified_at is None:
            raise ForbiddenError("Candidate email verification required")
        return user

    def _destination(self, phone: str) -> tuple[str, UUID]:
        # Bind to the current number without putting it in Redis metadata or keys.
        digest = hmac.new(
            self.settings.jwt_secret_key.encode(),
            ("mobile-verification:" + phone).encode(),
            hashlib.sha256,
        ).hexdigest()
        return digest, UUID(hex=digest[:32])

    def _available(self) -> None:
        if not self.settings.phone_otp_enabled:
            raise ServiceUnavailableError("Phone verification is temporarily unavailable")
        if self.settings.phone_otp_backend not in {"msg91", "sns"}:
            raise ServiceUnavailableError("Phone verification is not configured")

    async def request(self, user_id: UUID) -> MobileVerificationResponse:
        user = await self._owner(user_id)
        if user.phone_verified_at is not None:
            return MobileVerificationResponse(state="verified", phone_verified=True)
        if not user.phone:
            return MobileVerificationResponse(state="phone_required")
        self._available()
        phone = normalize_phone(user.phone, self.settings)
        fingerprint, destination = self._destination(phone)
        await self.otp.claim_send_cooldown(user.id)
        await self.otp.enforce_send_rate(user.id, "phone")
        await self.otp.enforce_send_rate(destination, "destination")
        for _ in range(8):
            code = generate_otp_code()
            if not await self.otp.matches_current_code(user.id, "phone", code):
                break
        else:
            raise ServiceUnavailableError("Phone verification is temporarily unavailable")
        await self.otp.clear(user.id, "phone")
        ttl = self.settings.signup_otp_ttl_seconds
        if self.msg91 is not None:
            ttl = min(ttl, self.settings.msg91_otp_expiry_minutes * 60)
            # Use SendOTP with a fresh canonical code, never /otp/retry (same code).
            await self.msg91.send_signup_otp(to_phone=phone, code=code)
        else:
            assert self.phone is not None
            await self.phone.send_signup_otp(
                to_phone=phone, code=code, ttl_minutes=max(1, ttl // 60)
            )
        await self.otp.store_otp(user.id, "phone", code)
        await self.otp.store_provider_state(
            user.id,
            "phone",
            {
                "destination": fingerprint,
                "expires_at": datetime.now(tz=UTC).timestamp() + ttl,
            },
        )
        await self.session.commit()
        return MobileVerificationResponse(
            state="code_sent",
            expires_in_seconds=ttl,
            resend_after_seconds=self.settings.signup_otp_resend_cooldown_seconds,
        )

    async def verify(self, user_id: UUID, code: str) -> MobileVerificationResponse:
        user = await self._owner(user_id)
        if user.phone_verified_at is not None:
            return MobileVerificationResponse(state="verified", phone_verified=True)
        if not user.phone:
            return MobileVerificationResponse(state="phone_required")
        self._available()
        await self.otp.enforce_verify_attempts(user.id)
        state = await self.otp.get_provider_state(user.id, "phone")
        phone = normalize_phone(user.phone, self.settings)
        fingerprint, _ = self._destination(phone)
        if (
            not state
            or state.get("destination") != fingerprint
            or not isinstance(state.get("expires_at"), (float, int))
            or state["expires_at"] <= datetime.now(tz=UTC).timestamp()
        ):
            await self.otp.clear(user.id, "phone")
            raise UnauthorizedError("Invalid or expired verification code")
        if not await self.otp.verify_and_consume(user.id, "phone", code):
            raise UnauthorizedError("Invalid or expired verification code")
        # Consume before the external validation and DB commit: failures stay unverified.
        await self.otp.clear(user.id, "phone")
        if self.msg91 is not None:
            await self.msg91.verify_signup_otp(to_phone=phone, code=code)
        user.phone_verified_at = datetime.now(tz=UTC)
        await self.session.commit()
        logger.info("account_mobile_verified", extra={"event": "account_mobile_verified"})
        return MobileVerificationResponse(state="verified", phone_verified=True)
