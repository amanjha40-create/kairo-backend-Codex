"""V1.1 security boundaries with synthetic local PostgreSQL records only."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.service import AuthService
from app.config import Settings
from app.core.constants import SignupKind
from app.exceptions import ConflictError, NotFoundError
from app.models import PendingSignup, RefreshToken, User, UserDocument
from app.models.passport_share_link import PassportShareLink
from app.models.passport_share_view import PassportShareView
from app.models.password_reset_token import PasswordResetToken
from app.models.permanent_address import PermanentAddressVersion
from app.repositories.password_reset_token import PasswordResetTokenRepository
from app.repositories.refresh_token import RefreshTokenRepository
from app.services.canonical_trust import resolve_identity
from app.services.passport_engine_service import PassportEngineService
from app.services.public_passport_service import PublicPassportService
from app.services.verification_request_service import VerificationRequestService


@pytest.fixture
async def local_db():
    url = make_url(os.environ["DATABASE_URL"])
    assert os.environ.get("V11_DISPOSABLE_DB") == "1", "Explicit disposable DB opt-in required"
    assert url.host in {"127.0.0.1", "localhost", "::1"}
    local_synthetic = url.database == "v11" and url.username == "qa"
    github_service = (
        os.environ.get("GITHUB_ACTIONS") == "true"
        and url.database == "kairo"
        and url.username == "kairo"
    )
    assert local_synthetic or github_service
    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        await session.execute(text("TRUNCATE users, pending_signups CASCADE"))
        await session.commit()
    try:
        yield factory
    finally:
        async with factory() as session:
            await session.execute(text("TRUNCATE users, pending_signups CASCADE"))
            await session.commit()
        await engine.dispose()


async def make_user(session):
    user = User(
        email=f"{uuid4()}@example.test",
        full_name="Synthetic QA",
        profile_slug=str(uuid4()),
        role="user",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


def document(user_id, **changes):
    values = dict(
        user_id=user_id,
        document_type="pan",
        object_key=f"qa/{uuid4()}",
        original_filename="synthetic.pdf",
        content_type="application/pdf",
        byte_size=123,
        checksum_sha256="a" * 64,
        verification_status="approved",
    )
    return UserDocument(**(values | changes))


async def test_completed_signup_is_not_a_login_credential():
    service = object.__new__(AuthService)
    service._issue_tokens = AsyncMock()
    pending = SimpleNamespace(signup_kind=SignupKind.CANDIDATE.value, completed_user_id=uuid4())
    with pytest.raises(ConflictError, match="already completed"):
        await service._complete_pending_signup(pending, SignupKind.CANDIDATE)
    service._issue_tokens.assert_not_called()


async def test_signup_restart_invalidates_old_capability_and_oauth_identity(local_db):
    async with local_db() as session:
        service = AuthService(session, Settings(), AsyncMock())
        service._otp = SimpleNamespace(clear_all=AsyncMock())
        pending = PendingSignup(
            email="restart@example.test",
            password_hash="synthetic",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            signup_kind=SignupKind.CANDIDATE,
            oauth_provider="google",
            oauth_provider_user_id="synthetic-old-subject",
        )
        session.add(pending)
        await session.commit()
        old_id = pending.id
        new = await service._get_or_prepare_pending_signup(
            email=pending.email,
            phone=None,
            full_name="Synthetic",
            password_hash="new-synthetic",
            signup_kind=SignupKind.CANDIDATE,
        )
        await session.commit()
        assert new.id != old_id
        assert new.oauth_provider is None and new.oauth_provider_user_id is None
        assert await session.get(PendingSignup, old_id) is None
        assert new.email_verified_at is None and new.phone_verified_at is None
        service._otp.clear_all.assert_awaited_once_with(old_id)
        with pytest.raises(NotFoundError):
            await service._load_active_pending(old_id)


@pytest.mark.parametrize("kind", ["reset", "refresh"])
async def test_one_time_token_consumption_serializes_and_reloads(local_db, kind):
    now = datetime.now(UTC)
    async with local_db() as session:
        user = await make_user(session)
        common = dict(user_id=user.id, token_hash="a" * 64, expires_at=now + timedelta(hours=1))
        row = (
            PasswordResetToken(**common)
            if kind == "reset"
            else RefreshToken(**common, family_id=uuid4())
        )
        session.add(row)
        await session.commit()
    async with local_db() as first, local_db() as second:

        async def acquire(session):
            if kind == "reset":
                return await PasswordResetTokenRepository(session).get_active_by_hash(
                    "a" * 64, now=now
                )
            return await RefreshTokenRepository(session).get_by_hash_any("a" * 64)

        held = await acquire(first)
        waiting = asyncio.create_task(acquire(second))
        await asyncio.sleep(0.1)
        assert not waiting.done()
        if kind == "reset":
            held.used_at = now
        else:
            held.revoked_at = now
        await first.commit()
        result = await asyncio.wait_for(waiting, 5)
        if kind == "reset":
            assert result is None
        else:
            assert result.revoked_at == now


@pytest.mark.parametrize("membership", [None, object()])
async def test_evidence_consent_precedes_metadata_and_url_serialization(membership):
    service = object.__new__(VerificationRequestService)
    request = SimpleNamespace(id=uuid4(), consented_evidence_scope=["certificate"])
    allowed = SimpleNamespace(evidence_type="certificate", field_key="degree")
    private = SimpleNamespace(evidence_type="bank_statement", field_key="private")
    service._get_access_context = AsyncMock(return_value=(request, membership, membership is None))
    service._evidence = SimpleNamespace(list_for_request=AsyncMock(return_value=[allowed, private]))
    service._to_evidence_response = AsyncMock(side_effect=lambda item, **kw: item)
    result = await service.list_evidence(uuid4(), "synthetic@example.test", uuid4())
    assert result == ([allowed, private] if membership is None else [allowed])
    assert service._to_evidence_response.await_count == len(result)


def test_mock_connector_is_not_registered_in_production(monkeypatch):
    from app.verification_connectors import providers

    monkeypatch.setattr(providers, "get_settings", lambda: SimpleNamespace(is_production=True))
    assert providers.get_connector_implementations() == ()
    monkeypatch.setattr(providers, "get_settings", lambda: SimpleNamespace(is_production=False))
    assert len(providers.get_connector_implementations()) == 1


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({}, "verified"),
        ({"expires_at": datetime.now(UTC).date()}, "verified"),
        ({"expires_at": datetime.now(UTC).date() - timedelta(days=1)}, "unverified"),
        ({"superseded_at": datetime.now(UTC)}, "unverified"),
        ({"deleted_at": datetime.now(UTC)}, "unverified"),
    ],
)
async def test_only_current_manual_identity_documents_count(local_db, changes, expected):
    async with local_db() as session:
        user = await make_user(session)
        session.add(document(user.id, **changes))
        await session.flush()
        assert (await resolve_identity(session, user))["state"] == expected


@pytest.mark.parametrize("inactive", [False, True])
async def test_public_vault_hides_historical_address_proofs(local_db, inactive):
    from app.api.v1.routes.public_vault import get_public_vault

    async with local_db() as session:
        user = await make_user(session)
        user.is_active = not inactive
        private = document(user.id)
        visible = document(user.id)
        session.add_all([private, visible])
        await session.flush()
        session.add(
            PermanentAddressVersion(
                user_id=user.id,
                version=1,
                claimed_address={},
                address_hash="b" * 64,
                document_id=private.id,
                invalidated_at=datetime.now(UTC),
            )
        )
        await session.flush()
        if inactive:
            with pytest.raises(NotFoundError):
                await get_public_vault(user.profile_slug, session)
        else:
            result = await get_public_vault(user.profile_slug, session)
            assert [d.id for d in result.user_documents] == [visible.id]


@pytest.mark.parametrize("state", ["active", "inactive", "deleted"])
async def test_public_passport_requires_current_active_owner(local_db, state):
    async with local_db() as session:
        user = await make_user(session)
        user.is_active = state != "inactive"
        user.deleted_at = datetime.now(UTC) if state == "deleted" else None
        service = PublicPassportService(session, Settings())
        link = PassportShareLink(owner_user_id=user.id, token_hash=service._hash_token("synthetic"))
        session.add(link)
        await session.flush()
        if state == "active":
            assert await service._resolve_active_share("synthetic") is link
        else:
            with pytest.raises(NotFoundError):
                await service._resolve_active_share("synthetic")


@pytest.mark.parametrize("count", [0, 1, 25])
async def test_passport_summary_query_count_is_constant_and_owner_scoped(local_db, count):
    async with local_db() as session:
        user = await make_user(session)
        other = await make_user(session)
        links = [
            PassportShareLink(owner_user_id=user.id, token_hash=f"{i:064x}") for i in range(count)
        ]
        foreign = PassportShareLink(owner_user_id=other.id, token_hash="f" * 64)
        session.add_all([*links, foreign])
        await session.flush()
        for link in [*links, foreign]:
            session.add_all(
                [
                    PassportShareView(share_id=link.id, viewer_ip_hash="a" * 64, is_unique_view=v)
                    for v in (True, False)
                ]
            )
        await session.commit()
        statements = []
        connection = (await session.connection()).sync_connection

        def collect(conn, cursor, statement, params, context, many):
            statements.append(statement)

        event.listen(connection, "before_cursor_execute", collect)
        try:
            result = await PassportEngineService(session, Settings())._build_sharing_summary(
                user.id
            )
        finally:
            event.remove(connection, "before_cursor_execute", collect)
        assert len(statements) == 2
        assert result.total_links == count and result.total_views == count * 2
        assert result.unique_views == count


async def test_suspension_waits_for_issuance_then_revokes_new_link(local_db):
    from app.schemas.admin_directory import AdminUserRestoreRequest, AdminUserSuspendRequest
    from app.services.admin_directory_service import AdminDirectoryService
    from app.services.private_owner_guard import lock_private_owner

    async with local_db() as session:
        user = await make_user(session)
        owner_id = user.id
        await session.commit()
    async with local_db() as issuance, local_db() as admin_session:
        await lock_private_owner(issuance, owner_id)
        service = AdminDirectoryService(admin_session, Settings())
        service._record_account_event = AsyncMock()
        service.get_user_detail = AsyncMock()
        actor = SimpleNamespace(id=owner_id)
        suspension = asyncio.create_task(
            service.suspend_user(
                actor, owner_id, AdminUserSuspendRequest(reason="Synthetic security test")
            )
        )
        await asyncio.sleep(0.1)
        assert not suspension.done()
        link = PassportShareLink(owner_user_id=owner_id, token_hash="d" * 64)
        issuance.add(link)
        await issuance.commit()
        await asyncio.wait_for(suspension, 5)
        await issuance.refresh(link)
        assert link.revoked_at is not None
        await issuance.refresh(user := await issuance.get(User, owner_id))
        assert not user.is_active
        await service.restore_user(
            actor, owner_id, AdminUserRestoreRequest(reason="Synthetic restoration")
        )
        await issuance.refresh(link)
        assert link.revoked_at is not None


async def test_security_revocation_includes_concurrent_rotation_successor(local_db):
    now = datetime.now(UTC)
    async with local_db() as session:
        user = await make_user(session)
        owner = user.id
        token = RefreshToken(
            user_id=owner,
            token_hash="b" * 64,
            family_id=uuid4(),
            expires_at=now + timedelta(hours=1),
        )
        session.add(token)
        await session.commit()
    async with local_db() as rotating, local_db() as resetting:
        repo = RefreshTokenRepository(rotating)
        old = await repo.get_by_hash_any("b" * 64)
        revocation = asyncio.create_task(
            RefreshTokenRepository(resetting).revoke_all_for_user(owner)
        )
        await asyncio.sleep(0.1)
        assert not revocation.done()
        old.revoked_at = now
        successor = RefreshToken(
            user_id=owner, token_hash="c" * 64, family_id=old.family_id, expires_at=old.expires_at
        )
        rotating.add(successor)
        await rotating.commit()
        await asyncio.wait_for(revocation, 5)
        await resetting.commit()
        await rotating.refresh(successor)
        assert successor.revoked_at is not None


async def test_signup_destination_rate_budget_survives_restart():
    from test_google_auth_lifecycle import _MemoryRedis

    from app.auth.signup_otp import SignupOtpStore, signup_rate_subject
    from app.exceptions import RateLimitError

    settings = Settings(signup_otp_max_sends_per_hour=2)
    redis = _MemoryRedis()
    store = SignupOtpStore(redis, settings)
    first = signup_rate_subject(settings, "email", "synthetic@example.test")
    await store.enforce_send_rate(first, "email")
    await store.enforce_send_rate(first, "email")
    restarted = signup_rate_subject(settings, "email", "synthetic@example.test")
    with pytest.raises(RateLimitError):
        await store.enforce_send_rate(restarted, "email")
    assert first == restarted
    assert all("synthetic@example.test" not in key for key in redis.values)
    assert first != signup_rate_subject(settings, "email", "other@example.test")


@pytest.mark.parametrize("operation", ["reset_issuance", "single_revoke", "password_login"])
async def test_other_token_mutators_follow_owner_first_order(local_db, operation):
    from app.repositories.token_owner import lock_token_owners
    from app.repositories.user import UserRepository

    now = datetime.now(UTC)
    async with local_db() as session:
        user = await make_user(session)
        owner, email = user.id, user.email
        token = RefreshToken(
            user_id=owner,
            token_hash="e" * 64,
            family_id=uuid4(),
            expires_at=now + timedelta(hours=1),
        )
        reset = PasswordResetToken(
            user_id=owner, token_hash="f" * 64, expires_at=now + timedelta(hours=1)
        )
        session.add_all([token, reset])
        await session.commit()
    async with local_db() as first, local_db() as second:
        await lock_token_owners(first, [owner])
        if operation == "reset_issuance":
            work = PasswordResetTokenRepository(second).mark_all_active_for_user_used(
                owner, used_at=now
            )
        elif operation == "single_revoke":
            work = RefreshTokenRepository(second).revoke(token.id)
        else:
            work = UserRepository(second).get_by_email(email, for_update=True)
        waiting = asyncio.create_task(work)
        await asyncio.sleep(0.1)
        assert not waiting.done()
        await first.commit()
        await asyncio.wait_for(waiting, 5)
        await second.commit()
