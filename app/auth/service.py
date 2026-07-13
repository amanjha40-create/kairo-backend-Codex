"""Authentication use cases — signup OTP, login, refresh with rotation."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.email_utils import mask_email, normalize_email
from app.auth.phone_utils import mask_phone, normalize_phone
from app.auth.provider_registry import get_provider
from app.auth.passwords import hash_password, password_needs_rehash, verify_password
from app.auth.signup_otp import SignupOtpStore, generate_otp_code
from app.auth.tokens import (
    create_access_token,
    generate_opaque_refresh_raw,
    hash_refresh_token,
)
from app.config import Settings
from app.core.constants import Role
from sqlalchemy.exc import IntegrityError

from app.exceptions import ConflictError, ForbiddenError, NotFoundError, UnauthorizedError
from app.integrations.email import get_email_sender
from app.integrations.phone_otp import get_phone_otp_sender
from app.models import PasswordResetToken, PendingSignup, RefreshToken, User
from app.models.user_social_account import UserSocialAccount
from app.repositories import PasswordResetTokenRepository, RefreshTokenRepository, UserRepository
from app.repositories.pending_signup import PendingSignupRepository
from app.repositories.user_social_account import UserSocialAccountRepository
from app.schemas.auth import (
    ChangePasswordRequest,
    ChangePasswordResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LinkProviderRequest,
    LinkProviderResponse,
    LoginRequest,
    OAuthAuthUrlResponse,
    OAuthCallbackRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    ResetPasswordResponse,
    SetPasswordRequest,
    SetPasswordResponse,
    SignupResendRequest,
    SignupResendResponse,
    SignupChannelRequest,
    SignupChannelSendResponse,
    SignupChannelVerifyResponse,
    SignupCompleteRequest,
    SignupStartResponse,
    SignupVerifyRequest,
    TokenResponse,
    UnlinkProviderResponse,
)

logger = logging.getLogger(__name__)
SignupChannel = Literal["email", "phone"]


def _make_slug(name: str | None, email: str) -> str:
    """Generate a URL-safe profile slug from name or email prefix."""
    base = name if name else email.split("@")[0]
    slug = base.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:60] or "user"


def _unique_slug(base: str) -> str:
    """Append a short random suffix to guarantee uniqueness."""
    suffix = uuid.uuid4().hex[:4]
    return f"{base}-{suffix}"


class AuthService:
    """Coordinates credential verification, signup OTP, and token lifecycle."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        redis: Redis,
    ) -> None:
        self._session = session
        self._settings = settings
        self._users = UserRepository(session)
        self._pending = PendingSignupRepository(session)
        self._password_resets = PasswordResetTokenRepository(session)
        self._refresh = RefreshTokenRepository(session)
        self._social = UserSocialAccountRepository(session)
        self._otp = SignupOtpStore(redis, settings)
        self._email = get_email_sender(settings)
        self._phone = get_phone_otp_sender(settings)

    async def start_signup(self, data: RegisterRequest) -> SignupStartResponse:
        """Create or replace a staged dual-channel signup session."""

        email = normalize_email(str(data.email))
        phone = normalize_phone(data.phone, self._settings)
        if await self._users.get_by_email(email) is not None or await self._users.get_by_phone(phone) is not None:
            raise ConflictError("An account already exists with this email or phone")

        pending = await self._get_or_prepare_pending_signup(
            email=email,
            phone=phone,
            full_name=data.full_name,
            password_hash=hash_password(data.password),
        )
        await self._session.commit()

        return SignupStartResponse(
            signup_session_id=pending.id,
            email_masked=mask_email(email),
            phone_masked=mask_phone(phone),
            email_verified=pending.email_verified_at is not None,
            phone_verified=pending.phone_verified_at is not None,
            email_resend_after_seconds=self._otp.seconds_until_resend_allowed(pending.email_last_otp_sent_at),
            phone_resend_after_seconds=self._otp.seconds_until_resend_allowed(pending.phone_last_otp_sent_at),
            expires_in_seconds=int((pending.expires_at - datetime.now(tz=UTC)).total_seconds()),
            message="Signup session created",
        )

    async def send_signup_email_otp(self, data: SignupChannelRequest) -> SignupChannelSendResponse:
        pending = await self._load_active_pending(data.signup_session_id)
        return await self._send_channel_otp(pending, "email")

    async def resend_signup_email_otp(self, data: SignupChannelRequest) -> SignupChannelSendResponse:
        pending = await self._load_active_pending(data.signup_session_id)
        self._otp.assert_resend_allowed(pending.email_last_otp_sent_at)
        return await self._send_channel_otp(pending, "email")

    async def verify_signup_email(self, data: SignupVerifyRequest) -> SignupChannelVerifyResponse:
        pending = await self._load_active_pending(data.signup_session_id)
        return await self._verify_channel_otp(pending, "email", data.code)

    async def send_signup_phone_otp(self, data: SignupChannelRequest) -> SignupChannelSendResponse:
        if not self._settings.phone_otp_enabled:
            raise ForbiddenError("Phone verification is not enabled")
        pending = await self._load_active_pending(data.signup_session_id)
        return await self._send_channel_otp(pending, "phone")

    async def resend_signup_phone_otp(self, data: SignupChannelRequest) -> SignupChannelSendResponse:
        if not self._settings.phone_otp_enabled:
            raise ForbiddenError("Phone verification is not enabled")
        pending = await self._load_active_pending(data.signup_session_id)
        self._otp.assert_resend_allowed(pending.phone_last_otp_sent_at)
        return await self._send_channel_otp(pending, "phone")

    async def verify_signup_phone(self, data: SignupVerifyRequest) -> SignupChannelVerifyResponse:
        if not self._settings.phone_otp_enabled:
            raise ForbiddenError("Phone verification is not enabled")
        pending = await self._load_active_pending(data.signup_session_id)
        return await self._verify_channel_otp(pending, "phone", data.code)

    async def complete_signup(self, data: SignupCompleteRequest) -> TokenResponse:
        pending = await self._load_active_pending(data.signup_session_id, allow_completed=True)
        if pending.completed_user_id is not None:
            user = await self._users.get_by_id(pending.completed_user_id)
            if user is None:
                raise ConflictError("Signup session is no longer valid")
            tokens = await self._issue_tokens(user)
            await self._session.commit()
            return tokens

        if pending.email_verified_at is None or pending.phone_verified_at is None:
            raise ConflictError("Both email and phone verification are required before signup completion")

        now = datetime.now(tz=UTC)
        slug_base = _make_slug(pending.full_name, pending.email)
        user = User(
            email=pending.email,
            phone=pending.phone,
            password_hash=pending.password_hash,
            full_name=pending.full_name,
            role=Role.USER.value,
            email_verified_at=pending.email_verified_at or now,
            phone_verified_at=pending.phone_verified_at or now,
            profile_slug=_unique_slug(slug_base),
        )
        self._session.add(user)

        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            user = await self._users.get_by_email(pending.email)
            if user is None and pending.phone:
                user = await self._users.get_by_phone(pending.phone)
            if user is None:
                raise ConflictError("An account already exists with this email or phone")
            if user.email != pending.email or (pending.phone and user.phone != pending.phone):
                raise ConflictError("An account already exists with this email or phone")
            pending = await self._load_active_pending(data.signup_session_id, allow_completed=True)
        else:
            pending.completed_user_id = user.id
            pending.completed_at = now

        if pending.completed_user_id is None:
            pending.completed_user_id = user.id
            pending.completed_at = now

        await self._otp.clear_all(pending.id)
        tokens = await self._issue_tokens(user)
        await self._session.commit()
        return tokens

    async def resend_signup_otp(self, data: SignupResendRequest) -> SignupResendResponse:
        response = await self.resend_signup_email_otp(SignupChannelRequest(signup_session_id=data.signup_session_id))
        return SignupResendResponse(
            signup_session_id=response.signup_session_id,
            email_masked=response.email_masked or "",
            resend_after_seconds=response.resend_after_seconds,
            message="Verification code sent",
        )

    async def verify_signup(self, data: SignupVerifyRequest) -> TokenResponse:
        result = await self.verify_signup_email(data)
        if not result.phone_verified:
            raise ConflictError("Phone verification is required before signup completion")
        return await self.complete_signup(SignupCompleteRequest(signup_session_id=data.signup_session_id))

    async def register(self, data: RegisterRequest) -> SignupStartResponse:
        """Backward-compatible alias for signup start (no tokens until OTP verify)."""

        return await self.start_signup(data)

    async def login(self, data: LoginRequest) -> TokenResponse:
        email = normalize_email(str(data.email))
        user = await self._users.get_by_email(email)
        if user is None:
            raise UnauthorizedError("Invalid credentials")
        if user.password_hash is None:
            # Account was created via Google — no password set
            raise UnauthorizedError("This account uses Google login. Please sign in with Google.")
        if not verify_password(data.password, user.password_hash):
            raise UnauthorizedError("Invalid credentials")
        if user.email_verified_at is None:
            raise ForbiddenError("Email not verified")
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(data.password)
            await self._session.flush()
        if not user.is_active:
            raise ForbiddenError("Account disabled")
        if user.deleted_at is not None:
            raise ForbiddenError("Account deleted")

        # Backfill a profile slug for accounts created before slugs existed.
        if not user.profile_slug:
            user.profile_slug = _unique_slug(_make_slug(user.full_name, user.email))

        tokens = await self._issue_tokens(user)
        await self._session.commit()
        return tokens

    async def forgot_password(self, data: ForgotPasswordRequest) -> ForgotPasswordResponse:
        email = normalize_email(str(data.email))
        user = await self._users.get_by_email(email)
        if (
            user is None
            or user.deleted_at is not None
            or not user.is_active
            or user.email_verified_at is None
        ):
            return ForgotPasswordResponse()

        now = datetime.now(tz=UTC)
        raw_token = generate_opaque_refresh_raw()
        token_hash = hash_refresh_token(raw_token)
        expires_at = now + timedelta(minutes=self._settings.password_reset_token_ttl_minutes)

        await self._password_resets.mark_all_active_for_user_used(user.id, used_at=now)
        await self._password_resets.create(
            PasswordResetToken(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=expires_at,
                used_at=None,
            )
        )

        try:
            await self._email.send_password_reset(
                to_email=user.email,
                reset_token=raw_token,
                ttl_minutes=self._settings.password_reset_token_ttl_minutes,
            )
        except Exception as exc:
            logger.warning(
                "password_reset_email_send_failed",
                extra={
                    "event": "password_reset_email_send_failed",
                    "user_id": str(user.id),
                    "to_email_domain": user.email.split("@")[-1] if "@" in user.email else "unknown",
                    "error_type": type(exc).__name__,
                },
            )

        await self._session.commit()
        return ForgotPasswordResponse()

    async def reset_password(self, data: ResetPasswordRequest) -> ResetPasswordResponse:
        now = datetime.now(tz=UTC)
        token = await self._password_resets.get_active_by_hash(
            hash_refresh_token(data.token.strip()),
            now=now,
        )
        if token is None:
            raise UnauthorizedError("Invalid or expired password reset token")

        user = await self._users.get_by_id(token.user_id)
        if user is None or user.deleted_at is not None or not user.is_active:
            raise UnauthorizedError("Invalid or expired password reset token")

        user.password_hash = hash_password(data.new_password)
        await self._password_resets.mark_used(token.id, used_at=now)
        await self._password_resets.mark_all_active_for_user_used(user.id, used_at=now)
        await self._refresh.revoke_all_for_user(user.id)
        await self._session.commit()
        return ResetPasswordResponse()

    async def refresh(self, data: RefreshRequest) -> TokenResponse:
        token_hash = hash_refresh_token(data.refresh_token)
        existing = await self._refresh.get_by_hash_any(token_hash)

        if existing is None:
            raise UnauthorizedError("Invalid refresh token")

        if existing.revoked_at is not None:
            await self._refresh.revoke_family(existing.family_id)
            await self._session.commit()
            raise UnauthorizedError("Refresh token reused")

        if existing.expires_at <= datetime.now(tz=UTC):
            raise UnauthorizedError("Refresh token expired")

        user = await self._users.get_by_id(existing.user_id)
        if user is None or not user.is_active or user.deleted_at is not None:
            raise UnauthorizedError("Invalid refresh token")
        if user.email_verified_at is None:
            raise UnauthorizedError("Invalid refresh token")

        await self._refresh.revoke(existing.id)

        raw_refresh = generate_opaque_refresh_raw()
        new_hash = hash_refresh_token(raw_refresh)
        expires = datetime.now(tz=UTC) + timedelta(days=self._settings.jwt_refresh_ttl_days)
        new_row = RefreshToken(
            user_id=user.id,
            token_hash=new_hash,
            expires_at=expires,
            family_id=existing.family_id,
            replaced_by_id=None,
        )
        self._session.add(new_row)
        await self._session.flush()

        access = create_access_token(self._settings, subject=user.id, role=user.role)
        ttl_sec = self._settings.jwt_access_ttl_minutes * 60
        tokens = TokenResponse(
            access_token=access,
            refresh_token=raw_refresh,
            expires_in=ttl_sec,
        )
        await self._session.commit()
        return tokens

    def get_oauth_url(self, provider_name: str) -> OAuthAuthUrlResponse:
        """Return the OAuth2 authorization URL for any supported provider."""

        provider = get_provider(provider_name)
        url = provider.get_auth_url(self._settings)
        return OAuthAuthUrlResponse(provider=provider_name, auth_url=url)

    async def oauth_callback(self, provider_name: str, data: OAuthCallbackRequest) -> TokenResponse:
        """Exchange auth code for app JWT tokens — works for any provider.

        Flow:
        1. Exchange code with provider → get normalised profile
        2. Look up social account row by (provider, provider_user_id)
        3a. Found → get linked user → issue tokens
        3b. Not found, email exists → link provider to existing user → issue tokens
        3c. Not found, new email → create user + social account → issue tokens
        """

        provider = get_provider(provider_name)

        try:
            profile = await provider.exchange_code(data.code, self._settings)
        except Exception as exc:
            # Log the actual reason for diagnosis (invalid_grant, redirect_uri_mismatch, etc.)
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                "oauth_exchange_failed",
                extra={
                    "event": "oauth_exchange_failed",
                    "provider": provider_name,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            raise UnauthorizedError(f"Failed to authenticate with {provider_name}") from exc

        email = normalize_email(profile.email)
        now = datetime.now(tz=UTC)

        # Try to find existing social account link
        social = await self._social.get_by_provider(provider_name, profile.provider_user_id)

        if social is not None:
            # Already linked — just load the user
            user = await self._users.get_by_id(social.user_id)
        else:
            # No link yet — find user by email or create new
            user = await self._users.get_by_email(email)

            if user is None:
                # Brand new user — create account (no password, email pre-verified)
                slug_base = _make_slug(profile.full_name, email)
                user = User(
                    email=email,
                    password_hash=None,
                    full_name=profile.full_name,
                    role=Role.USER.value,
                    email_verified_at=now,
                    profile_slug=_unique_slug(slug_base),
                )
                self._session.add(user)
                await self._session.flush()
            else:
                # Existing email account — auto-link this provider
                if user.email_verified_at is None:
                    user.email_verified_at = now

            # Create the social account link
            social = UserSocialAccount(
                user_id=user.id,
                provider=provider_name,
                provider_user_id=profile.provider_user_id,
                provider_email=email,
            )
            await self._social.create(social)

        if user is None or not user.is_active or user.deleted_at is not None:
            raise ForbiddenError("Account is disabled")

        # Backfill a profile slug for accounts created before slugs existed.
        if not user.profile_slug:
            user.profile_slug = _unique_slug(_make_slug(user.full_name, user.email))

        tokens = await self._issue_tokens(user)
        await self._session.commit()
        return tokens

    async def set_password(self, user_id: UUID, data: SetPasswordRequest) -> SetPasswordResponse:
        """Allow a social-only user to add a password so they can also use email login."""

        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")
        if user.password_hash is not None:
            raise ConflictError("A password is already set. Use change-password instead.")

        user.password_hash = hash_password(data.password)
        await self._session.commit()
        return SetPasswordResponse()

    async def change_password(self, user_id: UUID, data: ChangePasswordRequest) -> ChangePasswordResponse:
        """Change an existing password after verifying the current one."""

        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")
        if user.password_hash is None:
            raise ConflictError("No password is set. Use set-password instead.")
        if not verify_password(data.current_password, user.password_hash):
            raise UnauthorizedError("Current password is incorrect")

        user.password_hash = hash_password(data.new_password)
        await self._session.commit()
        return ChangePasswordResponse()

    async def link_provider(self, user_id: UUID, provider_name: str, data: LinkProviderRequest) -> LinkProviderResponse:
        """Link any OAuth provider to an existing account."""

        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")

        existing_link = await self._social.get_by_user_and_provider(user_id, provider_name)
        if existing_link is not None:
            raise ConflictError(f"{provider_name.capitalize()} account is already linked.")

        provider = get_provider(provider_name)

        try:
            profile = await provider.exchange_code(data.code, self._settings)
        except Exception as exc:
            raise UnauthorizedError(f"Failed to authenticate with {provider_name}") from exc

        # Make sure this provider account isn't linked to a different user
        conflict = await self._social.get_by_provider(provider_name, profile.provider_user_id)
        if conflict is not None and conflict.user_id != user_id:
            raise ConflictError(f"This {provider_name.capitalize()} account is already linked to another user.")

        social = UserSocialAccount(
            user_id=user_id,
            provider=provider_name,
            provider_user_id=profile.provider_user_id,
            provider_email=normalize_email(profile.email),
        )
        await self._social.create(social)
        await self._session.commit()
        return LinkProviderResponse(provider=provider_name, provider_email=profile.email)

    async def unlink_provider(self, user_id: UUID, provider_name: str) -> UnlinkProviderResponse:
        """Unlink an OAuth provider — requires password or another provider to remain."""

        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")

        social = await self._social.get_by_user_and_provider(user_id, provider_name)
        if social is None:
            raise NotFoundError(f"No {provider_name.capitalize()} account linked.")

        all_linked = await self._social.list_for_user(user_id)
        if user.password_hash is None and len(all_linked) <= 1:
            raise ConflictError(
                "Cannot unlink the only login method. Set a password first or link another provider."
            )

        await self._social.delete(social)
        await self._session.commit()
        return UnlinkProviderResponse(provider=provider_name)

    async def logout(self, data: RefreshRequest) -> None:
        """Revoke presented refresh token (best-effort idempotent)."""

        token_hash = hash_refresh_token(data.refresh_token)
        existing = await self._refresh.get_by_hash_any(token_hash)
        if existing and existing.revoked_at is None:
            await self._refresh.revoke(existing.id)
            await self._session.commit()

    async def _send_channel_otp(self, pending: PendingSignup, channel: SignupChannel) -> SignupChannelSendResponse:
        if channel == "email" and pending.email_verified_at is not None:
            return self._build_channel_send_response(pending, channel, verified=True, message="Email already verified")
        if channel == "phone" and pending.phone_verified_at is not None:
            return self._build_channel_send_response(pending, channel, verified=True, message="Phone already verified")

        code = generate_otp_code()
        await self._otp.enforce_send_rate(pending.id, channel)
        await self._otp.store_otp(pending.id, channel, code)
        ttl_minutes = max(1, self._settings.signup_otp_ttl_seconds // 60)
        if channel == "email":
            await self._email.send_signup_otp(to_email=pending.email, code=code, ttl_minutes=ttl_minutes)
            pending.email_otp_sent_count += 1
            pending.email_last_otp_sent_at = datetime.now(tz=UTC)
        else:
            await self._phone.send_signup_otp(to_phone=pending.phone or "", code=code, ttl_minutes=ttl_minutes)
            pending.phone_otp_sent_count += 1
            pending.phone_last_otp_sent_at = datetime.now(tz=UTC)
        await self._session.flush()
        await self._session.commit()
        return self._build_channel_send_response(pending, channel, verified=False, message="Verification code sent")

    async def _verify_channel_otp(
        self,
        pending: PendingSignup,
        channel: SignupChannel,
        code: str,
    ) -> SignupChannelVerifyResponse:
        attempt_count = pending.email_verify_attempt_count if channel == "email" else pending.phone_verify_attempt_count
        if attempt_count >= self._settings.signup_otp_max_verify_attempts:
            raise UnauthorizedError("Invalid or expired verification code")

        normalized_code = code.strip()
        if len(normalized_code) != 6 or not normalized_code.isdigit():
            raise UnauthorizedError("Invalid or expired verification code")

        if channel == "email" and pending.email_verified_at is not None:
            return self._build_channel_verify_response(pending, channel, message="Email already verified")
        if channel == "phone" and pending.phone_verified_at is not None:
            return self._build_channel_verify_response(pending, channel, message="Phone already verified")

        ok = await self._otp.verify_and_consume(pending.id, channel, normalized_code)
        if not ok:
            if channel == "email":
                pending.email_verify_attempt_count += 1
            else:
                pending.phone_verify_attempt_count += 1
            await self._session.commit()
            raise UnauthorizedError("Invalid or expired verification code")

        now = datetime.now(tz=UTC)
        if channel == "email":
            pending.email_verified_at = now
        else:
            pending.phone_verified_at = now
        await self._session.commit()
        return self._build_channel_verify_response(pending, channel, message=f"{channel.capitalize()} verified")

    async def _load_active_pending(self, signup_session_id: UUID, allow_completed: bool = False) -> PendingSignup:
        pending = await self._pending.get_by_id(signup_session_id)
        if pending is None:
            raise NotFoundError("Signup session not found")
        if allow_completed and pending.completed_user_id is not None:
            return pending
        if await self._pending.is_expired(pending):
            await self._otp.clear_all(pending.id)
            await self._pending.delete_by_id(pending.id)
            await self._session.commit()
            raise UnauthorizedError("Invalid or expired verification code")
        return pending

    async def _get_or_prepare_pending_signup(
        self,
        *,
        email: str,
        phone: str,
        full_name: str | None,
        password_hash: str,
    ) -> PendingSignup:
        pending_by_email = await self._pending.get_by_email(email)
        pending_by_phone = await self._pending.get_by_phone(phone)

        cleared_any = False
        seen_pending_ids: set[UUID] = set()
        for attr_name, row in [("email", pending_by_email), ("phone", pending_by_phone)]:
            if row is None or row.id in seen_pending_ids:
                continue
            seen_pending_ids.add(row.id)
            if row is not None and row.completed_user_id is None and await self._pending.is_expired(row):
                await self._otp.clear_all(row.id)
                await self._pending.delete_by_id(row.id)
                cleared_any = True
                if attr_name == "email":
                    pending_by_email = None
                else:
                    pending_by_phone = None
        if cleared_any:
            await self._session.flush()

        if pending_by_email is not None and pending_by_email.completed_user_id is not None:
            raise ConflictError("An account already exists with this email or phone")
        if pending_by_phone is not None and pending_by_phone.completed_user_id is not None:
            raise ConflictError("An account already exists with this email or phone")

        pending_ids = {row.id for row in [pending_by_email, pending_by_phone] if row is not None}
        if len(pending_ids) > 1:
            raise ConflictError("A signup is already pending for this email or phone")

        expires_at = datetime.now(tz=UTC) + timedelta(hours=self._settings.signup_pending_ttl_hours)
        pending = pending_by_email or pending_by_phone
        if pending is None:
            pending = PendingSignup(
                email=email,
                phone=phone,
                password_hash=password_hash,
                full_name=full_name,
                expires_at=expires_at,
                email_verified_at=None,
                phone_verified_at=None,
                email_otp_sent_count=0,
                email_verify_attempt_count=0,
                email_last_otp_sent_at=None,
                phone_otp_sent_count=0,
                phone_verify_attempt_count=0,
                phone_last_otp_sent_at=None,
            )
            self._session.add(pending)
        else:
            await self._otp.clear_all(pending.id)
            pending.email = email
            pending.phone = phone
            pending.password_hash = password_hash
            pending.full_name = full_name
            pending.expires_at = expires_at
            pending.email_verified_at = None
            pending.phone_verified_at = None
            pending.email_otp_sent_count = 0
            pending.email_verify_attempt_count = 0
            pending.email_last_otp_sent_at = None
            pending.phone_otp_sent_count = 0
            pending.phone_verify_attempt_count = 0
            pending.phone_last_otp_sent_at = None
            pending.completed_user_id = None
            pending.completed_at = None

        await self._session.flush()
        return pending

    def _build_channel_send_response(
        self,
        pending: PendingSignup,
        channel: SignupChannel,
        *,
        verified: bool,
        message: str,
    ) -> SignupChannelSendResponse:
        return SignupChannelSendResponse(
            signup_session_id=pending.id,
            channel=channel,
            verified=verified,
            email_verified=pending.email_verified_at is not None,
            phone_verified=pending.phone_verified_at is not None,
            resend_after_seconds=(
                self._otp.seconds_until_resend_allowed(pending.email_last_otp_sent_at)
                if channel == "email"
                else self._otp.seconds_until_resend_allowed(pending.phone_last_otp_sent_at)
            ),
            expires_in_seconds=self._settings.signup_otp_ttl_seconds,
            email_masked=mask_email(pending.email),
            phone_masked=mask_phone(pending.phone or ""),
            message=message,
        )

    def _build_channel_verify_response(
        self,
        pending: PendingSignup,
        channel: SignupChannel,
        *,
        message: str,
    ) -> SignupChannelVerifyResponse:
        return SignupChannelVerifyResponse(
            signup_session_id=pending.id,
            channel=channel,
            email_verified=pending.email_verified_at is not None,
            phone_verified=pending.phone_verified_at is not None,
            message=message,
        )

    async def _issue_tokens(self, user: User) -> TokenResponse:
        raw_refresh = generate_opaque_refresh_raw()
        token_hash = hash_refresh_token(raw_refresh)
        family_id = uuid.uuid4()
        expires = datetime.now(tz=UTC) + timedelta(days=self._settings.jwt_refresh_ttl_days)
        row = RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires,
            family_id=family_id,
        )
        self._session.add(row)
        await self._session.flush()

        access = create_access_token(self._settings, subject=user.id, role=user.role)
        ttl_sec = self._settings.jwt_access_ttl_minutes * 60
        return TokenResponse(
            access_token=access,
            refresh_token=raw_refresh,
            expires_in=ttl_sec,
        )
