"""Database lifecycle coverage for native Sign in with Apple."""

from __future__ import annotations

import base64
import json
import os
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.auth.service as auth_service_module
import app.services.account_deletion_service as account_deletion_module
from app.auth.providers.apple import AppleIdentity, AppleTokenExchange
from app.auth.service import AuthService
from app.config import Settings
from app.models import PendingSignup, RefreshToken, User, UserSocialAccount
from app.schemas.auth import AppleSignInRequest, GoogleAuthOutcome
from app.services.account_deletion_service import AccountDeletionService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]
TEST_DATABASE_URL = os.environ["DATABASE_URL"]


class _MemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value
        self.ttls[key] = ex

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def delete(self, *keys: str) -> int:
        for key in keys:
            self.values.pop(key, None)
            self.ttls.pop(key, None)
        return len(keys)

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -1)

    async def eval(self, *_args: Any, **_kwargs: Any) -> int:
        return 1


def _settings() -> Settings:
    key = base64.b64encode(b"a" * 32).decode()
    return Settings(
        app_env="test",
        database_url=TEST_DATABASE_URL,
        jwt_secret_key="test-jwt-secret-key-32-chars-minimum!!",
        phone_otp_backend="console",
        apple_client_id="com.kairoid.Kairo",
        apple_team_id="MVT4T97ZGC",
        apple_key_id="TESTKEY123",
        apple_private_key="test-only-not-used",
        digilocker_token_encryption_active_key_id="test-key",
        digilocker_token_encryption_keys=json.dumps({"test-key": key}),
    )


def _request() -> AppleSignInRequest:
    return AppleSignInRequest(
        identity_token="signed-identity-token-for-tests",
        authorization_code="one-time-authorization-code",
        nonce="raw-nonce-with-sufficient-test-entropy",
        given_name="Relay",
        family_name="Candidate",
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


def _provider_mocks(monkeypatch: pytest.MonkeyPatch, *, subject: str, email: str) -> list[str]:
    exchanges: list[str] = []
    monkeypatch.setattr(
        auth_service_module,
        "validate_apple_identity_token",
        lambda *_args: AppleIdentity(provider_user_id=subject, email=email),
    )

    async def exchange(code: str, _settings: Settings) -> AppleTokenExchange:
        exchanges.append(code)
        return AppleTokenExchange(refresh_token="synthetic-apple-refresh-token")

    monkeypatch.setattr(auth_service_module, "exchange_apple_authorization_code", exchange)
    return exchanges


async def test_new_apple_identity_uses_private_relay_and_requires_phone(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    exchanges = _provider_mocks(
        monkeypatch,
        subject="apple-stable-subject",
        email="relay@privaterelay.appleid.com",
    )
    async with session_factory() as session:
        service = AuthService(session, _settings(), _MemoryRedis())
        result = await service.sign_in_with_apple(_request())
        assert result.outcome is GoogleAuthOutcome.PHONE_VERIFICATION_REQUIRED
        assert result.signup is not None
        assert result.tokens is None
        assert exchanges == ["one-time-authorization-code"]

        pending = await session.get(PendingSignup, result.signup.signup_session_id)
        assert pending is not None
        assert pending.email == "relay@privaterelay.appleid.com"
        assert pending.full_name == "Relay Candidate"
        assert pending.oauth_provider == "apple"
        assert pending.oauth_provider_user_id == "apple-stable-subject"
        assert pending.oauth_refresh_token_encrypted is not None
        assert "synthetic-apple-refresh-token" not in repr(pending.oauth_refresh_token_encrypted)


async def test_existing_email_is_never_silently_merged(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    exchanges = _provider_mocks(
        monkeypatch,
        subject="different-apple-subject",
        email="existing@example.com",
    )
    async with session_factory() as session:
        session.add(
            User(
                email="existing@example.com",
                phone="+919876540000",
                password_hash="hashed-password",
                full_name="Existing Candidate",
                role="user",
                is_active=True,
                email_verified_at=datetime.now(tz=UTC),
                phone_verified_at=datetime.now(tz=UTC),
                profile_slug="existing-candidate",
            )
        )
        await session.commit()
        service = AuthService(session, _settings(), _MemoryRedis())
        result = await service.sign_in_with_apple(_request())
        assert result.outcome is GoogleAuthOutcome.ACCOUNT_LINKING_REQUIRED
        assert result.tokens is None
        assert result.signup is None
        assert exchanges == []
        social_count = await session.scalar(select(func.count()).select_from(UserSocialAccount))
        assert int(social_count or 0) == 0
        assert int(await session.scalar(select(func.count()).select_from(RefreshToken)) or 0) == 0


async def test_returning_linked_apple_subject_restores_session_and_rotates_revocation_token(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    exchanges = _provider_mocks(
        monkeypatch,
        subject="returning-apple-subject",
        email="relay@privaterelay.appleid.com",
    )
    async with session_factory() as session:
        user = User(
            email="relay@privaterelay.appleid.com",
            phone="+919876540001",
            password_hash=None,
            full_name="Returning Candidate",
            role="user",
            is_active=True,
            email_verified_at=datetime.now(tz=UTC),
            phone_verified_at=datetime.now(tz=UTC),
            profile_slug="returning-candidate",
        )
        session.add(user)
        await session.flush()
        social = UserSocialAccount(
            user_id=user.id,
            provider="apple",
            provider_user_id="returning-apple-subject",
            provider_email="relay@privaterelay.appleid.com",
        )
        session.add(social)
        await session.commit()

        service = AuthService(session, _settings(), _MemoryRedis())
        result = await service.sign_in_with_apple(_request())
        assert result.outcome is GoogleAuthOutcome.LOGIN_COMPLETE
        assert result.tokens is not None
        assert exchanges == ["one-time-authorization-code"]
        await session.refresh(social)
        assert social.encrypted_refresh_token is not None
        decrypted = service._provider_token_cipher().decrypt_secret(
            social.encrypted_refresh_token,
            user_id=user.id,
            connection_id=social.id,
            purpose="refresh_token",
            provider="apple",
        )
        assert decrypted.get_secret_value() == "synthetic-apple-refresh-token"


async def test_failed_code_exchange_creates_no_pending_identity(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auth_service_module,
        "validate_apple_identity_token",
        lambda *_args: AppleIdentity(
            provider_user_id="failed-exchange-subject",
            email="failed-exchange@privaterelay.appleid.com",
        ),
    )

    async def fail_exchange(*_args: Any) -> AppleTokenExchange:
        raise ValueError("synthetic exchange failure")

    monkeypatch.setattr(auth_service_module, "exchange_apple_authorization_code", fail_exchange)
    async with session_factory() as session:
        service = AuthService(session, _settings(), _MemoryRedis())
        result = await service.sign_in_with_apple(_request())
        assert result.outcome is GoogleAuthOutcome.AUTH_FAILED
        assert int(await session.scalar(select(func.count()).select_from(PendingSignup)) or 0) == 0
        social_count = await session.scalar(select(func.count()).select_from(UserSocialAccount))
        assert int(social_count or 0) == 0


async def test_account_deletion_revokes_decrypted_apple_refresh_token(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    revoked: list[str] = []

    async def record_revocation(token: str, _settings: Settings) -> None:
        revoked.append(token)

    monkeypatch.setattr(account_deletion_module, "revoke_apple_refresh_token", record_revocation)
    async with session_factory() as session:
        user = User(
            email="delete-relay@privaterelay.appleid.com",
            phone="+919876540002",
            password_hash=None,
            full_name="Delete Candidate",
            role="user",
            is_active=True,
            email_verified_at=datetime.now(tz=UTC),
            phone_verified_at=datetime.now(tz=UTC),
            profile_slug="delete-candidate",
        )
        session.add(user)
        await session.flush()
        social = UserSocialAccount(
            user_id=user.id,
            provider="apple",
            provider_user_id="delete-apple-subject",
            provider_email=user.email,
        )
        session.add(social)
        await session.flush()
        auth = AuthService(session, _settings(), _MemoryRedis())
        social.encrypted_refresh_token = auth._provider_token_cipher().encrypt_secret(
            SecretStr("refresh-token-to-revoke"),
            user_id=user.id,
            connection_id=social.id,
            purpose="refresh_token",
            provider="apple",
        )
        await session.commit()

        deletion = AccountDeletionService(session, _settings(), _MemoryRedis())
        await deletion._revoke_apple_credentials(user.id)
        assert revoked == ["refresh-token-to-revoke"]
