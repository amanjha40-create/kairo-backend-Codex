from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config.settings import AppEnvironment
from app.core.constants import Role
from app.models import AdminAccessAuditEvent, RefreshToken, User
from app.ops.bootstrap_first_superadmin import (
    BootstrapCommandRefused,
    parser,
    validate_execution_contract,
)
from app.services.first_superadmin_bootstrap import (
    BOOTSTRAP_AUDIT_ACTION,
    FirstSuperadminBootstrapRefused,
    FirstSuperadminBootstrapService,
)

pytestmark = pytest.mark.integration
TARGET_ID = UUID("efe561b2-10ed-48d0-9315-31307ec93ef5")
TARGET_EMAIL = "aman@kairoid.com"
PERSONAL_ADMIN_EMAIL = "amanjha40@gmail.com"
SOURCE_SHA = "9" * 40


@pytest.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    from os import environ

    engine = create_async_engine(environ["DATABASE_URL"], pool_pre_ping=True, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
async def reset_database(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE admin_access_audit_events, refresh_tokens, users "
                "RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()
    yield


def user(
    *,
    user_id: UUID | None = None,
    email: str,
    role: str = Role.ADMIN.value,
    active: bool = True,
    verified: bool = True,
) -> User:
    return User(
        id=user_id or uuid4(),
        email=email,
        password_hash="test-password-hash",
        full_name="Bootstrap Test",
        role=role,
        is_active=active,
        email_verified_at=datetime.now(tz=UTC) if verified else None,
    )


def token(owner: User) -> RefreshToken:
    return RefreshToken(
        user_id=owner.id,
        token_hash=uuid4().hex + uuid4().hex,
        expires_at=datetime.now(tz=UTC) + timedelta(days=7),
        family_id=uuid4(),
    )


async def seed_valid_state(session: AsyncSession) -> tuple[User, User, RefreshToken, RefreshToken]:
    target = user(user_id=TARGET_ID, email=TARGET_EMAIL)
    personal = user(email=PERSONAL_ADMIN_EMAIL)
    target_token = token(target)
    personal_token = token(personal)
    session.add_all([target, personal, target_token, personal_token])
    await session.flush()
    return target, personal, target_token, personal_token


async def promote(session: AsyncSession):
    return await FirstSuperadminBootstrapService(session).promote(
        target_user_id=TARGET_ID,
        target_email=TARGET_EMAIL,
        expected_current_role=Role.ADMIN.value,
        environment=AppEnvironment.PRODUCTION.value,
        source_sha=SOURCE_SHA,
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_promotes_same_admin_row_without_duplicate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        target, _, _, _ = await seed_valid_state(session)
        result = await promote(session)
        assert result.target_user_id == target.id == result.administrator_id
        assert result.prior_role == Role.ADMIN.value
        assert result.new_role == Role.SUPERADMIN.value

    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(User)) == 2
        saved = await session.get(User, TARGET_ID)
        assert saved is not None and saved.role == Role.SUPERADMIN.value


@pytest.mark.asyncio(loop_scope="session")
async def test_audit_persisted_and_only_target_sessions_revoked(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        _, personal, target_token, personal_token = await seed_valid_state(session)
        result = await promote(session)
        assert result.sessions_revoked == 1

    async with session_factory() as session:
        audit = await session.scalar(
            select(AdminAccessAuditEvent).where(
                AdminAccessAuditEvent.action == BOOTSTRAP_AUDIT_ACTION
            )
        )
        assert audit is not None
        assert audit.subject_user_id == TARGET_ID
        assert audit.metadata_payload["target_user_id"] == str(TARGET_ID)
        assert audit.metadata_payload["administrator_id"] == str(TARGET_ID)
        assert audit.metadata_payload["prior_role"] == Role.ADMIN.value
        assert audit.metadata_payload["new_role"] == Role.SUPERADMIN.value
        assert audit.metadata_payload["environment"] == AppEnvironment.PRODUCTION.value
        assert audit.metadata_payload["source_sha"] == SOURCE_SHA
        assert audit.metadata_payload["execution_context"] == "bootstrap_first_superadmin_cli"
        assert (await session.get(RefreshToken, target_token.id)).revoked_at is not None
        assert (await session.get(RefreshToken, personal_token.id)).revoked_at is None
        untouched = await session.get(User, personal.id)
        assert untouched is not None and untouched.role == Role.ADMIN.value


@pytest.mark.asyncio(loop_scope="session")
async def test_existing_active_superadmin_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        await seed_valid_state(session)
        session.add(user(email="existing-superadmin@example.com", role=Role.SUPERADMIN.value))
        await session.flush()
        with pytest.raises(FirstSuperadminBootstrapRefused, match="active_superadmin_exists"):
            await promote(session)


@pytest.mark.asyncio(loop_scope="session")
async def test_target_role_not_admin_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        session.add(user(user_id=TARGET_ID, email=TARGET_EMAIL, role=Role.HR.value))
        await session.flush()
        with pytest.raises(FirstSuperadminBootstrapRefused, match="target_role_changed"):
            await promote(session)


@pytest.mark.parametrize("mismatch", ["id", "email"])
@pytest.mark.asyncio(loop_scope="session")
async def test_target_identity_mismatch_rejected(
    session_factory: async_sessionmaker[AsyncSession],
    mismatch: str,
) -> None:
    async with session_factory() as session, session.begin():
        target = user(user_id=TARGET_ID, email=TARGET_EMAIL)
        session.add(target)
        await session.flush()
        service = FirstSuperadminBootstrapService(session)
        with pytest.raises(FirstSuperadminBootstrapRefused):
            await service.promote(
                target_user_id=uuid4() if mismatch == "id" else TARGET_ID,
                target_email="other@example.com" if mismatch == "email" else TARGET_EMAIL,
                expected_current_role=Role.ADMIN.value,
                environment=AppEnvironment.PRODUCTION.value,
                source_sha=SOURCE_SHA,
            )


@pytest.mark.parametrize(
    ("active", "verified", "reason"),
    [(False, True, "target_inactive"), (True, False, "target_unverified")],
)
@pytest.mark.asyncio(loop_scope="session")
async def test_inactive_or_unverified_target_rejected(
    session_factory: async_sessionmaker[AsyncSession],
    active: bool,
    verified: bool,
    reason: str,
) -> None:
    async with session_factory() as session, session.begin():
        session.add(
            user(
                user_id=TARGET_ID,
                email=TARGET_EMAIL,
                active=active,
                verified=verified,
            )
        )
        await session.flush()
        with pytest.raises(FirstSuperadminBootstrapRefused, match=reason):
            await promote(session)


@pytest.mark.asyncio(loop_scope="session")
async def test_deleted_target_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        target = user(user_id=TARGET_ID, email=TARGET_EMAIL)
        target.deleted_at = datetime.now(tz=UTC)
        session.add(target)
        await session.flush()
        with pytest.raises(FirstSuperadminBootstrapRefused, match="target_deleted"):
            await promote(session)


@pytest.mark.asyncio(loop_scope="session")
async def test_concurrent_superadmin_appearance_rolls_back(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with session_factory() as seed_session, seed_session.begin():
        target, _, _, _ = await seed_valid_state(seed_session)
        target_id = target.id

    async with session_factory() as session:
        service = FirstSuperadminBootstrapService(session)
        original_lock = service._lock_staff_rows

        async def introduce_superadmin_then_lock() -> None:
            async with session_factory() as competing, competing.begin():
                other = await competing.scalar(
                    select(User).where(User.email == PERSONAL_ADMIN_EMAIL).with_for_update()
                )
                other.role = Role.SUPERADMIN.value
            await original_lock()

        monkeypatch.setattr(service, "_lock_staff_rows", introduce_superadmin_then_lock)
        with pytest.raises(FirstSuperadminBootstrapRefused, match="active_superadmin_exists"):
            async with session.begin():
                await service.promote(
                    target_user_id=target_id,
                    target_email=TARGET_EMAIL,
                    expected_current_role=Role.ADMIN.value,
                    environment=AppEnvironment.PRODUCTION.value,
                    source_sha=SOURCE_SHA,
                )

    async with session_factory() as session:
        unchanged = await session.get(User, target_id)
        assert unchanged is not None and unchanged.role == Role.ADMIN.value
        assert await session.scalar(
            select(func.count())
            .select_from(AdminAccessAuditEvent)
            .where(AdminAccessAuditEvent.action == BOOTSTRAP_AUDIT_ACTION)
        ) == 0


@pytest.mark.asyncio(loop_scope="session")
async def test_second_run_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        await seed_valid_state(session)
        await promote(session)

    async with session_factory() as session:
        with pytest.raises(FirstSuperadminBootstrapRefused):
            async with session.begin():
                await promote(session)


def test_cli_requires_all_explicit_arguments() -> None:
    with pytest.raises(SystemExit):
        parser().parse_args([])


def test_cli_contract_requires_production_runtime_and_source_sha() -> None:
    args = parser().parse_args(
        [
            "--target-user-id",
            str(TARGET_ID),
            "--target-email",
            TARGET_EMAIL,
            "--expected-current-role",
            Role.ADMIN.value,
            "--environment",
            AppEnvironment.PRODUCTION.value,
            "--confirm-first-superadmin-bootstrap",
        ]
    )
    production = SimpleNamespace(
        app_env=AppEnvironment.PRODUCTION,
        app_git_sha=SOURCE_SHA,
    )
    assert validate_execution_contract(production, args) == SOURCE_SHA

    with pytest.raises(
        BootstrapCommandRefused,
        match="runtime_environment_not_production",
    ):
        validate_execution_contract(
            SimpleNamespace(app_env=AppEnvironment.STAGING, app_git_sha=SOURCE_SHA), args
        )
    with pytest.raises(BootstrapCommandRefused, match="source_sha_unavailable"):
        validate_execution_contract(
            SimpleNamespace(app_env=AppEnvironment.PRODUCTION, app_git_sha=None), args
        )
