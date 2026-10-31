"""Secure first-password creation for federated accounts."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401
from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_auth_service
from app.auth.password_errors import (
    InvalidCurrentPasswordError,
    InvalidSetPasswordChallengeError,
    PasswordAlreadySetError,
    PasswordNotSetError,
    SetPasswordNotEligibleError,
)
from app.auth.passwords import hash_password, verify_password
from app.auth.service import AuthService
from app.auth.signup_otp import SignupOtpStore
from app.auth.tokens import decode_token_safe
from app.config import Settings
from app.exceptions import RateLimitError
from app.infrastructure.redis.deps import get_redis
from app.main import app
from app.models import User, UserAccountEvent, UserSocialAccount
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    SetPasswordRequest,
    SetPasswordResponse,
    SetPasswordVerificationResponse,
)
from app.services.user_service import UserService

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.integration]
TEST_DATABASE_URL = os.environ["DATABASE_URL"]
FIRST_PASSWORD = "FirstPassword123!"
SECOND_PASSWORD = "SecondPassword123!"


class MemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int,
        nx: bool = False,
    ) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.ttls[key] = ex
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if self.values.pop(key, None) is not None:
                removed += 1
            self.ttls.pop(key, None)
        return removed

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -1)

    async def eval(self, script: str, _key_count: int, key: str, *args: str) -> Any:
        if "stored ~= ARGV[1]" in script:
            if self.values.get(key) != args[0]:
                return 0
            await self.delete(key)
            return 1
        count = int(self.values.get(key, "0")) + 1
        self.values[key] = str(count)
        self.ttls.setdefault(key, int(args[0]) if args else 3600)
        return count


class CapturingEmail:
    def __init__(self) -> None:
        self.deliveries: list[dict[str, object]] = []

    async def send_set_password_otp(self, **payload: object) -> None:
        self.deliveries.append(payload)


def settings() -> Settings:
    return Settings(
        app_env="test",
        database_url=TEST_DATABASE_URL,
        jwt_secret_key="test-jwt-secret-key-32-chars-minimum!!",
        signup_otp_ttl_seconds=600,
        signup_otp_resend_cooldown_seconds=30,
        signup_otp_max_verify_attempts=3,
        signup_otp_max_sends_per_hour=3,
    )


@pytest.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True, poolclass=NullPool)
    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
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


async def create_user(
    session: AsyncSession,
    *,
    password_hash: str | None = None,
    linked: bool = True,
    verified: bool = True,
) -> User:
    user = User(
        email=f"federated-{uuid4()}@example.com",
        password_hash=password_hash,
        full_name="Federated Candidate",
        role="user",
        is_active=True,
        email_verified_at=datetime.now(tz=UTC) if verified else None,
        profile_slug=f"federated-{uuid4().hex}",
    )
    session.add(user)
    await session.flush()
    if linked:
        session.add(
            UserSocialAccount(
                user_id=user.id,
                provider="google",
                provider_user_id=f"google-{uuid4()}",
                provider_email=user.email,
            )
        )
    await session.commit()
    return user


def service(session: AsyncSession, redis: MemoryRedis) -> tuple[AuthService, CapturingEmail]:
    auth = AuthService(session, settings(), redis)  # type: ignore[arg-type]
    email = CapturingEmail()
    auth._email = email  # type: ignore[assignment]
    auth._notify_password_changed = AsyncMock()
    return auth, email


async def test_google_only_account_securely_sets_first_password_and_keeps_link(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    redis = MemoryRedis()
    async with session_factory() as session:
        user = await create_user(session)
        user_id = user.id
        user_email = user.email
        auth, email = service(session, redis)

        before = await UserService(session, settings()).get_public_profile(user_id)
        assert before.has_password is False

        requested = await auth.request_set_password(user_id)
        assert requested.email_masked != user_email
        assert email.deliveries[0]["to_email"] == user_email
        code = str(email.deliveries[0]["code"])
        assert code not in requested.model_dump_json()

        with pytest.raises(InvalidSetPasswordChallengeError) as invalid:
            await auth.set_password(
                user_id,
                SetPasswordRequest(
                    code="000000",
                    password=FIRST_PASSWORD,
                    confirm_password=FIRST_PASSWORD,
                ),
            )
        assert invalid.value.code == "invalid_or_expired_challenge"
        await session.rollback()

        await auth.set_password(
            user_id,
            SetPasswordRequest(
                code=code,
                password=FIRST_PASSWORD,
                confirm_password=FIRST_PASSWORD,
            ),
        )
        user = await session.get(User, user_id)
        assert user is not None
        assert user.password_hash is not None
        assert verify_password(FIRST_PASSWORD, user.password_hash)

        after = await UserService(session, settings()).get_public_profile(user_id)
        assert after.has_password is True
        assert await session.scalar(select(func.count()).select_from(User)) == 1
        social = await session.scalar(
            select(UserSocialAccount).where(UserSocialAccount.user_id == user_id)
        )
        assert social is not None and social.provider == "google"

        tokens = await auth.login(LoginRequest(email=user_email, password=FIRST_PASSWORD))
        claims = decode_token_safe(settings(), tokens.access_token)
        assert claims is not None and claims["sub"] == str(user_id)

        event = await session.scalar(
            select(UserAccountEvent).where(
                UserAccountEvent.user_id == user_id,
                UserAccountEvent.event_type == "password_set",
            )
        )
        assert event is not None and event.actor_user_id == user_id
        auth._notify_password_changed.assert_awaited_once_with(user_id, event.id)


async def test_set_password_challenge_is_purpose_bound_one_time_and_expiring(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    redis = MemoryRedis()
    async with session_factory() as session:
        user = await create_user(session)
        user_id = user.id
        auth, email = service(session, redis)
        await auth.request_set_password(user_id)
        valid_code = str(email.deliveries[0]["code"])

        signup_scope = SignupOtpStore(redis, settings(), scope="signup")  # type: ignore[arg-type]
        await signup_scope.store_otp(user_id, "email", "654321")
        with pytest.raises(InvalidSetPasswordChallengeError):
            await auth.set_password(
                user_id,
                SetPasswordRequest(
                    code="654321",
                    password=FIRST_PASSWORD,
                    confirm_password=FIRST_PASSWORD,
                ),
            )
        await session.rollback()

        assert await auth._set_password_otp.verify_and_consume(user_id, "email", valid_code)
        with pytest.raises(InvalidSetPasswordChallengeError):
            await auth.set_password(
                user_id,
                SetPasswordRequest(
                    code=valid_code,
                    password=FIRST_PASSWORD,
                    confirm_password=FIRST_PASSWORD,
                ),
            )
        await session.rollback()

        await auth._set_password_otp.store_otp(user_id, "email", "123456")
        await auth._set_password_otp.clear(user_id, "email")
        with pytest.raises(InvalidSetPasswordChallengeError):
            await auth.set_password(
                user_id,
                SetPasswordRequest(
                    code="123456",
                    password=FIRST_PASSWORD,
                    confirm_password=FIRST_PASSWORD,
                ),
            )


async def test_set_password_challenge_is_bound_to_authenticated_account(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    redis = MemoryRedis()
    async with session_factory() as session:
        first_user = await create_user(session)
        second_user = await create_user(session)
        auth, email = service(session, redis)
        await auth.request_set_password(first_user.id)
        first_user_code = str(email.deliveries[0]["code"])

        with pytest.raises(InvalidSetPasswordChallengeError):
            await auth.set_password(
                second_user.id,
                SetPasswordRequest(
                    code=first_user_code,
                    password=FIRST_PASSWORD,
                    confirm_password=FIRST_PASSWORD,
                ),
            )

        second_user = await session.get(User, second_user.id)
        assert second_user is not None and second_user.password_hash is None


async def test_set_password_request_and_verify_limits_are_enforced(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    redis = MemoryRedis()
    async with session_factory() as session:
        user = await create_user(session)
        user_id = user.id
        auth, _ = service(session, redis)
        await auth.request_set_password(user_id)
        with pytest.raises(RateLimitError):
            await auth.request_set_password(user_id)

        for _ in range(settings().signup_otp_max_verify_attempts):
            with pytest.raises(InvalidSetPasswordChallengeError):
                await auth.set_password(
                    user_id,
                    SetPasswordRequest(
                        code="000000",
                        password=FIRST_PASSWORD,
                        confirm_password=FIRST_PASSWORD,
                    ),
                )
            await session.rollback()
        with pytest.raises(RateLimitError):
            await auth.set_password(
                user_id,
                SetPasswordRequest(
                    code="000000",
                    password=FIRST_PASSWORD,
                    confirm_password=FIRST_PASSWORD,
                ),
            )


@pytest.mark.parametrize(
    ("linked", "verified"),
    [(False, True), (True, False)],
)
async def test_ineligible_account_cannot_request_first_password(
    session_factory: async_sessionmaker[AsyncSession],
    linked: bool,
    verified: bool,
) -> None:
    async with session_factory() as session:
        user = await create_user(session, linked=linked, verified=verified)
        auth, _ = service(session, MemoryRedis())
        with pytest.raises(SetPasswordNotEligibleError):
            await auth.request_set_password(user.id)


async def test_race_or_second_set_never_overwrites_existing_password(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    redis = MemoryRedis()
    async with session_factory() as session:
        user = await create_user(session)
        auth, email = service(session, redis)
        await auth.request_set_password(user.id)
        user.password_hash = hash_password(SECOND_PASSWORD)
        await session.commit()

        with pytest.raises(PasswordAlreadySetError) as error:
            await auth.set_password(
                user.id,
                SetPasswordRequest(
                    code=str(email.deliveries[0]["code"]),
                    password=FIRST_PASSWORD,
                    confirm_password=FIRST_PASSWORD,
                ),
            )
        assert error.value.code == "password_already_set"
        await session.refresh(user)
        assert verify_password(SECOND_PASSWORD, user.password_hash or "")


async def test_google_plus_password_uses_normal_change_password_without_revocation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user = await create_user(session, password_hash=hash_password(FIRST_PASSWORD))
        user_id = user.id
        auth, _ = service(session, MemoryRedis())
        auth._refresh.revoke_all_for_user = AsyncMock()

        with pytest.raises(InvalidCurrentPasswordError) as error:
            await auth.change_password(
                user_id,
                ChangePasswordRequest(
                    current_password="WrongPassword123!",
                    new_password=SECOND_PASSWORD,
                    confirm_password=SECOND_PASSWORD,
                ),
            )
        assert error.value.code == "invalid_current_password"
        await session.rollback()

        await auth.change_password(
            user_id,
            ChangePasswordRequest(
                current_password=FIRST_PASSWORD,
                new_password=SECOND_PASSWORD,
                confirm_password=SECOND_PASSWORD,
            ),
        )
        user = await session.get(User, user_id)
        assert user is not None
        assert verify_password(SECOND_PASSWORD, user.password_hash or "")
        auth._refresh.revoke_all_for_user.assert_not_awaited()
        assert await session.scalar(
            select(func.count()).select_from(UserSocialAccount).where(
                UserSocialAccount.user_id == user_id
            )
        ) == 1
        assert await session.scalar(
            select(func.count()).select_from(UserAccountEvent).where(
                UserAccountEvent.user_id == user_id,
                UserAccountEvent.event_type == "password_changed",
            )
        ) == 1


async def test_federated_only_account_cannot_use_change_password(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user = await create_user(session)
        auth, _ = service(session, MemoryRedis())

        with pytest.raises(PasswordNotSetError) as error:
            await auth.change_password(
                user.id,
                ChangePasswordRequest(
                    current_password="NonexistentPassword123!",
                    new_password=FIRST_PASSWORD,
                    confirm_password=FIRST_PASSWORD,
                ),
            )

        assert error.value.code == "password_not_set"


async def test_first_password_schema_preserves_password_policy() -> None:
    with pytest.raises(ValidationError):
        SetPasswordRequest(code="123456", password="short", confirm_password="short")
    with pytest.raises(ValidationError):
        SetPasswordRequest(
            code="123456",
            password=FIRST_PASSWORD,
            confirm_password=SECOND_PASSWORD,
        )


class RouteAuth:
    def __init__(self) -> None:
        self.requested: list[object] = []
        self.confirmed: list[object] = []

    async def request_set_password(self, user_id: object) -> SetPasswordVerificationResponse:
        self.requested.append(user_id)
        return SetPasswordVerificationResponse(
            email_masked="f***@example.com",
            expires_in_seconds=600,
            resend_after_seconds=30,
        )

    async def set_password(self, user_id: object, payload: object) -> SetPasswordResponse:
        self.confirmed.append((user_id, payload))
        return SetPasswordResponse()


async def test_set_password_routes_require_request_then_code_contract() -> None:
    route_auth = RouteAuth()
    principal = CurrentUser(id=uuid4(), email="federated@example.com", role="user")
    redis = MemoryRedis()
    app.dependency_overrides[get_auth_service] = lambda: route_auth
    app.dependency_overrides[get_current_user] = lambda: principal
    app.dependency_overrides[get_redis] = lambda: redis
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            requested = await client.post("/api/v1/auth/set-password/request")
            missing_code = await client.post(
                "/api/v1/auth/set-password",
                json={"password": FIRST_PASSWORD, "confirm_password": FIRST_PASSWORD},
            )
            confirmed = await client.post(
                "/api/v1/auth/set-password",
                json={
                    "code": "123456",
                    "password": FIRST_PASSWORD,
                    "confirm_password": FIRST_PASSWORD,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert requested.status_code == 200
    assert missing_code.status_code == 422
    assert confirmed.status_code == 200
    assert route_auth.requested == [principal.id]
    assert len(route_auth.confirmed) == 1


async def test_openapi_exposes_first_password_and_capability_contracts() -> None:
    app.openapi_schema = None
    schema = app.openapi()

    assert "/api/v1/auth/set-password/request" in schema["paths"]
    assert "/api/v1/auth/set-password" in schema["paths"]
    request_schema = schema["components"]["schemas"]["SetPasswordRequest"]
    assert set(request_schema["required"]) == {"code", "password", "confirm_password"}
    assert request_schema["properties"]["code"]["pattern"] == "^[0-9]{6}$"
    assert schema["components"]["schemas"]["UserPublic"]["properties"]["has_password"][
        "type"
    ] == "boolean"
