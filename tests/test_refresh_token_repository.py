from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401
from app.api.dependencies.auth import get_optional_current_user
from app.auth.tokens import create_access_token
from app.config import get_settings
from app.db.session import get_session
from app.main import app
from app.models import RefreshToken, User
from app.repositories import RefreshTokenRepository
from app.schemas.admin_session import AdminSessionResponse

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]
TEST_DATABASE_URL = os.environ["DATABASE_URL"]


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
async def reset_database(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await session.execute(text("TRUNCATE TABLE refresh_tokens, users RESTART IDENTITY CASCADE"))
        await session.commit()
    yield
    async with session_factory() as session:
        await session.execute(text("TRUNCATE TABLE refresh_tokens, users RESTART IDENTITY CASCADE"))
        await session.commit()


async def _create_user(
    session: AsyncSession,
    *,
    role: str = "user",
) -> User:
    user = User(
        email=f"{role}-{uuid4().hex[:8]}@example.com",
        password_hash="hashed-password",
        full_name=f"{role.title()} User",
        role=role,
        is_active=True,
        email_verified_at=datetime.now(tz=UTC),
    )
    session.add(user)
    await session.flush()
    return user


async def _create_refresh_token(
    session: AsyncSession,
    *,
    user_id: UUID,
    family_id: UUID,
    revoked_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> RefreshToken:
    row = RefreshToken(
        user_id=user_id,
        token_hash=uuid4().hex,
        expires_at=expires_at or (datetime.now(tz=UTC) + timedelta(days=7)),
        family_id=family_id,
        revoked_at=revoked_at,
        replaced_by_id=None,
    )
    session.add(row)
    await session.flush()
    return row


@pytest.mark.asyncio
async def test_has_active_family_returns_false_when_no_tokens_exist(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user = await _create_user(session)
        repo = RefreshTokenRepository(session)

        assert await repo.has_active_family(user.id, uuid4()) is False


@pytest.mark.asyncio
async def test_has_active_family_returns_true_for_exactly_one_active_token(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user = await _create_user(session)
        family_id = uuid4()
        await _create_refresh_token(session, user_id=user.id, family_id=family_id)
        repo = RefreshTokenRepository(session)

        assert await repo.has_active_family(user.id, family_id) is True


@pytest.mark.asyncio
async def test_has_active_family_returns_true_for_multiple_active_tokens_without_exception(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user = await _create_user(session)
        family_id = uuid4()
        await _create_refresh_token(session, user_id=user.id, family_id=family_id)
        await _create_refresh_token(session, user_id=user.id, family_id=family_id)
        repo = RefreshTokenRepository(session)

        assert await repo.has_active_family(user.id, family_id) is True


@pytest.mark.asyncio
async def test_has_active_family_returns_false_for_revoked_tokens_only(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user = await _create_user(session)
        family_id = uuid4()
        await _create_refresh_token(
            session,
            user_id=user.id,
            family_id=family_id,
            revoked_at=datetime.now(tz=UTC) - timedelta(minutes=1),
        )
        repo = RefreshTokenRepository(session)

        assert await repo.has_active_family(user.id, family_id) is False


@pytest.mark.asyncio
async def test_has_active_family_returns_false_for_expired_tokens_only(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user = await _create_user(session)
        family_id = uuid4()
        await _create_refresh_token(
            session,
            user_id=user.id,
            family_id=family_id,
            expires_at=datetime.now(tz=UTC) - timedelta(minutes=1),
        )
        repo = RefreshTokenRepository(session)

        assert await repo.has_active_family(user.id, family_id) is False


@pytest.mark.asyncio
async def test_has_active_family_returns_true_when_family_has_active_and_inactive_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user = await _create_user(session)
        family_id = uuid4()
        await _create_refresh_token(
            session,
            user_id=user.id,
            family_id=family_id,
            revoked_at=datetime.now(tz=UTC) - timedelta(minutes=1),
        )
        await _create_refresh_token(
            session,
            user_id=user.id,
            family_id=family_id,
            expires_at=datetime.now(tz=UTC) - timedelta(minutes=1),
        )
        await _create_refresh_token(session, user_id=user.id, family_id=family_id)
        repo = RefreshTokenRepository(session)

        assert await repo.has_active_family(user.id, family_id) is True


@pytest.mark.asyncio
async def test_has_active_family_isolated_by_family_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user = await _create_user(session)
        active_family_id = uuid4()
        other_family_id = uuid4()
        await _create_refresh_token(session, user_id=user.id, family_id=active_family_id)
        repo = RefreshTokenRepository(session)

        assert await repo.has_active_family(user.id, active_family_id) is True
        assert await repo.has_active_family(user.id, other_family_id) is False


@pytest.mark.asyncio
async def test_get_optional_current_user_accepts_multiple_active_tokens_in_same_family(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        settings = get_settings()
        user = await _create_user(session)
        family_id = uuid4()
        await _create_refresh_token(session, user_id=user.id, family_id=family_id)
        await _create_refresh_token(session, user_id=user.id, family_id=family_id)
        token = create_access_token(
            settings,
            subject=user.id,
            role=user.role,
            extra_claims={"sid": str(family_id)},
        )

        current = await get_optional_current_user(
            credentials=type(
                "BearerCredentials",
                (),
                {"scheme": "Bearer", "credentials": token},
            )(),
            session=session,
            settings=settings,
        )

        assert current is not None
        assert current.id == user.id
        assert current.session_family_id == family_id


@pytest.mark.asyncio
async def test_admin_session_route_stays_healthy_with_multiple_active_family_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        settings = get_settings()
        admin = await _create_user(session, role="admin")
        family_id = uuid4()
        await _create_refresh_token(session, user_id=admin.id, family_id=family_id)
        await _create_refresh_token(session, user_id=admin.id, family_id=family_id)
        await session.commit()

        token = create_access_token(
            settings,
            subject=admin.id,
            role=admin.role,
            extra_claims={"sid": str(family_id)},
        )

        async def override_session():
            yield session

        app.dependency_overrides[get_session] = override_session
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.get(
                    "/api/v1/admin/session",
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = AdminSessionResponse.model_validate(response.json())
    assert payload.account.email == admin.email
    assert payload.account.role_key == "admin"
    assert "access_admin_portal" in payload.account.permissions
