"""Real AuthService/PostgreSQL lifecycle coverage for Google Candidate signup."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401
import app.auth.service as auth_service_module
from app.auth.providers.base import OAuthProfile
from app.auth.service import AuthService
from app.config import Settings
from app.exceptions.base import ConflictError, UnauthorizedError
from app.models import PendingSignup, RefreshToken, User, UserSocialAccount
from app.schemas.auth import (
    GoogleAuthOutcome,
    GooglePhoneStartRequest,
    SignupChannelRequest,
    SignupCompleteRequest,
    SignupVerifyRequest,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]
TEST_DATABASE_URL = os.environ["DATABASE_URL"]


class _MemoryRedis:
    """Implements the small Redis subset exercised by OAuth and signup OTP stores."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value
        self.ttls[key] = ex

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if self.values.pop(key, None) is not None:
                deleted += 1
            self.ttls.pop(key, None)
        return deleted

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -1)

    async def eval(self, script: str, _keys: int, key: str, *args: str) -> Any:
        # OAuth handoff/state consume atomically reads and deletes a value.
        if "GET" in script and "DEL" in script and "ARGV" not in script:
            self.ttls.pop(key, None)
            return self.values.pop(key, None)
        # OTP verification compares the stored hash before consuming it.
        if "stored ~= ARGV[1]" in script:
            expected = args[0]
            if self.values.get(key) != expected:
                return 0
            await self.delete(key)
            return 1
        # OTP send rate limiting increments a counter with an expiry.
        count = int(self.values.get(key, "0")) + 1
        self.values[key] = str(count)
        self.ttls.setdefault(key, 3600)
        return count


class _PhoneDelivery:
    """External SMS boundary only: the deterministic code stays inside the OTP service."""

    code = "123456"

    def __init__(self) -> None:
        self.deliveries: list[tuple[str, str]] = []

    def challenge_code(self, *, to_phone: str, generated_code: str) -> str:
        del to_phone, generated_code
        return self.code

    async def send_signup_otp(self, *, to_phone: str, code: str, ttl_minutes: int) -> None:
        del ttl_minutes
        self.deliveries.append((to_phone, code))


class _GoogleProvider:
    def __init__(self, profile: OAuthProfile) -> None:
        self.profile = profile
        self.exchanged_codes: list[str] = []

    def get_auth_url(self, *_args: Any, **_kwargs: Any) -> str:
        return "https://accounts.google.test/authorize"

    async def exchange_code(self, code: str, *_args: Any, **_kwargs: Any) -> OAuthProfile:
        self.exchanged_codes.append(code)
        return self.profile


def _settings() -> Settings:
    return Settings(
        app_env="test",
        database_url=TEST_DATABASE_URL,
        jwt_secret_key="test-jwt-secret-key-32-chars-minimum!!",
        phone_otp_backend="console",
        google_client_id="google-lifecycle-test-client.apps.googleusercontent.com",
        google_client_secret="not-a-real-secret",
        google_redirect_uri="https://staging-api.kairoid.com/api/v1/auth/google/callback",
        google_app_handoff_uri="https://staging-api.kairoid.com/auth/google/complete",
    )


@pytest.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
async def reset_database(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        await session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
        await session.commit()
    yield
    async with session_factory() as session:
        await session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
        await session.commit()


async def _count(session: AsyncSession, model: type[Any]) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def _make_service(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    profile: OAuthProfile,
) -> tuple[AuthService, _PhoneDelivery, _GoogleProvider]:
    provider = _GoogleProvider(profile)
    monkeypatch.setattr(auth_service_module, "get_provider", lambda provider_name: provider)
    service = AuthService(session, _settings(), _MemoryRedis())
    phone = _PhoneDelivery()
    service._phone = phone
    return service, phone, provider


async def _complete_google_callback(service: AuthService) -> tuple[str, Any]:
    transaction = await service._oauth_transactions.create()
    handoff_code = await service.complete_google_callback(
        code="external-google-authorization-code",
        state=transaction.state,
    )
    return handoff_code, await service.exchange_google_handoff(handoff_code)


async def _create_user(session: AsyncSession, *, email: str, phone: str = "+919876540000") -> User:
    user = User(
        email=email,
        phone=phone,
        password_hash="hashed-password",
        full_name="Lifecycle Candidate",
        role="user",
        is_active=True,
        email_verified_at=datetime.now(tz=UTC),
        phone_verified_at=datetime.now(tz=UTC),
        profile_slug=f"lifecycle-{email.split('@')[0]}",
    )
    session.add(user)
    await session.flush()
    return user


async def test_linked_google_identity_issues_session_without_mutating_identity(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = OAuthProfile(
        provider_user_id="lifecycle-linked-sub",
        email="linked.lifecycle@example.com",
        full_name="Linked Lifecycle",
        email_verified=True,
    )
    async with session_factory() as session:
        user = await _create_user(session, email=profile.email)
        session.add(
            UserSocialAccount(
                user_id=user.id,
                provider="google",
                provider_user_id=profile.provider_user_id,
                provider_email=profile.email,
            )
        )
        await session.commit()

        service, _phone, provider = await _make_service(session, monkeypatch, profile)
        _handoff, result = await _complete_google_callback(service)

        assert provider.exchanged_codes == ["external-google-authorization-code"]
        assert result.outcome is GoogleAuthOutcome.LOGIN_COMPLETE
        assert result.tokens is not None
        assert result.tokens.access_token
        assert result.tokens.refresh_token
        assert result.signup is None
        assert await _count(session, User) == 1
        assert await _count(session, UserSocialAccount) == 1
        assert await _count(session, PendingSignup) == 0
        assert await _count(session, RefreshToken) == 1


async def test_new_google_identity_requires_phone_and_same_email_fails_closed(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with session_factory() as session:
        new_profile = OAuthProfile(
            provider_user_id="lifecycle-new-sub",
            email="new.lifecycle@example.com",
            full_name="New Lifecycle",
            email_verified=True,
        )
        service, _phone, _provider = await _make_service(session, monkeypatch, new_profile)
        _handoff, result = await _complete_google_callback(service)

        assert result.outcome is GoogleAuthOutcome.PHONE_VERIFICATION_REQUIRED
        assert result.tokens is None
        assert result.signup is not None
        pending = await session.get(PendingSignup, result.signup.signup_session_id)
        assert pending is not None
        assert pending.oauth_provider == "google"
        assert pending.oauth_provider_user_id == "lifecycle-new-sub"
        assert pending.oauth_provider_email == "new.lifecycle@example.com"
        assert pending.oauth_validated_at is not None
        assert pending.email_verified_at is not None
        assert await _count(session, User) == 0
        assert await _count(session, UserSocialAccount) == 0
        assert await _count(session, RefreshToken) == 0

    async with session_factory() as session:
        profile = OAuthProfile(
            provider_user_id="lifecycle-unlinked-sub",
            email="collision.lifecycle@example.com",
            full_name="Collision Lifecycle",
            email_verified=True,
        )
        await _create_user(session, email=profile.email)
        await session.commit()
        service, _phone, _provider = await _make_service(session, monkeypatch, profile)
        _handoff, result = await _complete_google_callback(service)

        assert result.outcome is GoogleAuthOutcome.ACCOUNT_LINKING_REQUIRED
        assert result.tokens is None
        assert result.signup is None
        assert await _count(session, User) == 1
        assert await _count(session, UserSocialAccount) == 0
        collision_pending = await session.scalar(
            select(PendingSignup).where(PendingSignup.email == profile.email)
        )
        assert collision_pending is None
        assert await _count(session, RefreshToken) == 0


async def test_google_pending_signup_uses_phone_otp_before_single_completion(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = OAuthProfile(
        provider_user_id="lifecycle-phone-sub",
        email="phone.lifecycle@example.com",
        full_name="Phone Lifecycle",
        email_verified=True,
    )
    async with session_factory() as session:
        service, phone, _provider = await _make_service(session, monkeypatch, profile)
        callback_handoff, handoff = await _complete_google_callback(service)
        assert handoff.outcome is GoogleAuthOutcome.PHONE_VERIFICATION_REQUIRED
        assert handoff.signup is not None
        signup_id = handoff.signup.signup_session_id

        # A consumed App Link handoff cannot be replayed to obtain another continuation.
        replay = await service.exchange_google_handoff(callback_handoff)
        assert replay.outcome is GoogleAuthOutcome.AUTH_FAILED

        await service.start_google_phone_verification(
            GooglePhoneStartRequest(signup_session_id=signup_id, phone="+919876543210")
        )
        await service.send_signup_phone_otp(SignupChannelRequest(signup_session_id=signup_id))
        assert phone.deliveries == [("+919876543210", "123456")]

        # Neither completion nor an incorrect code can create the Candidate or a Google link.
        with pytest.raises(ConflictError, match="Both email and phone verification"):
            await service.complete_signup(SignupCompleteRequest(signup_session_id=signup_id))
        with pytest.raises(UnauthorizedError, match="Invalid or expired"):
            await service.verify_signup_phone(SignupVerifyRequest(signup_session_id=signup_id, code="654321"))
        pending = await session.get(PendingSignup, signup_id)
        assert pending is not None
        assert pending.phone_verified_at is None
        assert pending.phone_verify_attempt_count == 1
        assert await _count(session, User) == 0
        assert await _count(session, UserSocialAccount) == 0
        assert await _count(session, RefreshToken) == 0

        verified = await service.verify_signup_phone(
            SignupVerifyRequest(signup_session_id=signup_id, code="123456")
        )
        assert verified.phone_verified is True
        tokens = await service.complete_signup(SignupCompleteRequest(signup_session_id=signup_id))
        assert tokens.access_token
        assert tokens.refresh_token

        pending = await session.get(PendingSignup, signup_id)
        assert pending is not None
        assert pending.completed_user_id is not None
        assert pending.phone_verified_at is not None
        assert pending.oauth_provider is None
        assert pending.oauth_provider_user_id is None
        assert pending.oauth_provider_email is None
        user = await session.get(User, pending.completed_user_id)
        assert user is not None
        assert user.email == profile.email
        assert user.phone == "+919876543210"
        assert user.email_verified_at is not None
        assert user.phone_verified_at is not None
        assert await _count(session, User) == 1
        assert await _count(session, UserSocialAccount) == 1
        assert await _count(session, RefreshToken) == 1

        # Canonical completion replay issues a fresh session for the same completed user only.
        replay_tokens = await service.complete_signup(SignupCompleteRequest(signup_session_id=signup_id))
        assert replay_tokens.access_token
        assert replay_tokens.refresh_token
        assert await _count(session, User) == 1
        assert await _count(session, UserSocialAccount) == 1
        assert await _count(session, RefreshToken) == 2
