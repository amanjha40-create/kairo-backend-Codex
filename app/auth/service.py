"""Authentication use cases — signup OTP, login, refresh with rotation."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.email_utils import mask_email, normalize_email
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
    SignupStartResponse,
    SignupVerifyRequest,
    TokenResponse,
    UnlinkProviderResponse,
)

logger = logging.getLogger(__name__)


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

    async def start_signup(self, data: RegisterRequest) -> SignupStartResponse:
        """Stage signup and email a 6-digit OTP — no JWT until verify."""

        email = normalize_email(str(data.email))
        if await self._users.get_by_email(email) is not None:
            raise ConflictError("Email already registered")

        await self._otp.enforce_send_rate(email)
        await self._pending.delete_by_email(email)

        expires_at = datetime.now(tz=UTC) + timedelta(hours=self._settings.signup_pending_ttl_hours)
        pending = PendingSignup(
            email=email,
            password_hash=hash_password(data.password),
            full_name=data.full_name,
            expires_at=expires_at,
            otp_sent_count=0,
            verify_attempt_count=0,
            last_otp_sent_at=None,
        )
        self._session.add(pending)
        await self._session.flush()

        await self._send_otp(pending)
        await self._session.commit()

        return SignupStartResponse(
            signup_session_id=pending.id,
            email_masked=mask_email(email),
            resend_after_seconds=self._settings.signup_otp_resend_cooldown_seconds,
            expires_in_seconds=self._settings.signup_otp_ttl_seconds,
            message="Verification code sent",
        )

    async def resend_signup_otp(self, data: SignupResendRequest) -> SignupResendResponse:
        pending = await self._load_active_pending(data.signup_session_id)
        self._otp.assert_resend_allowed(pending.last_otp_sent_at)
        await self._otp.enforce_send_rate(pending.email)
        await self._send_otp(pending)
        await self._session.commit()
        return SignupResendResponse(
            signup_session_id=pending.id,
            email_masked=mask_email(pending.email),
            resend_after_seconds=self._settings.signup_otp_resend_cooldown_seconds,
            message="Verification code sent",
        )

    async def verify_signup(self, data: SignupVerifyRequest) -> TokenResponse:
        pending = await self._load_active_pending(data.signup_session_id)

        # Check attempt cap before touching Redis — no side effects on cap exceeded.
        if pending.verify_attempt_count >= self._settings.signup_otp_max_verify_attempts:
            raise UnauthorizedError("Invalid or expired verification code")

        code = data.code.strip()
        # Bad format → reject without burning an attempt (not a real guess).
        if len(code) != 6 or not code.isdigit():
            raise UnauthorizedError("Invalid or expired verification code")

        # Atomically verify + consume OTP (Lua).  Only a wrong *valid-format* code
        # increments the attempt counter, preventing format-based lockout attacks.
        ok = await self._otp.verify_and_consume(pending.email, code)
        if not ok:
            pending.verify_attempt_count += 1
            await self._session.commit()
            raise UnauthorizedError("Invalid or expired verification code")

        # Single transaction: create user + delete pending signup.
        # Catch IntegrityError in case a concurrent request raced to the same email.
        now = datetime.now(tz=UTC)
        slug_base = _make_slug(pending.full_name, pending.email)
        user = User(
            email=pending.email,
            password_hash=pending.password_hash,
            full_name=pending.full_name,
            role=Role.USER.value,
            email_verified_at=now,
            profile_slug=_unique_slug(slug_base),
        )
        self._session.add(user)
        await self._pending.delete_by_id(pending.id)

        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            raise ConflictError("Email already registered")

        tokens = await self._issue_tokens(user)
        await self._session.commit()
        return tokens

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

    async def _send_otp(self, pending: PendingSignup) -> None:
        code = generate_otp_code()
        await self._otp.store_otp(pending.email, code)
        ttl_minutes = max(1, self._settings.signup_otp_ttl_seconds // 60)
        await self._email.send_signup_otp(to_email=pending.email, code=code, ttl_minutes=ttl_minutes)
        pending.otp_sent_count += 1
        pending.last_otp_sent_at = datetime.now(tz=UTC)
        await self._session.flush()

    async def _load_active_pending(self, signup_session_id: UUID) -> PendingSignup:
        pending = await self._pending.get_by_id(signup_session_id)
        if pending is None:
            raise NotFoundError("Signup session not found")
        if await self._pending.is_expired(pending):
            await self._otp.clear(pending.email)
            await self._pending.delete_by_id(pending.id)
            await self._session.commit()
            raise UnauthorizedError("Invalid or expired verification code")
        return pending

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
