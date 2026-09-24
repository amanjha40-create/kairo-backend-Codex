"""Real local PostgreSQL/Redis lifecycle tests; provider calls are always mocked."""

import asyncio
import base64
import hashlib
import json
import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from digilocker_helpers import grant, provider, settings
from pydantic import SecretStr
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.auth.passwords import hash_password
from app.config import get_settings
from app.db.session import async_session_factory
from app.exceptions import (
    ConflictError,
    ForbiddenError,
    ServiceUnavailableError,
    ValidationAppError,
)
from app.integrations.digilocker.provider import DigiLockerProvider, ProviderError
from app.integrations.digilocker.transactions import StateError, TransactionStore
from app.models import DigiLockerConnection, User
from app.schemas.account_deletion import AccountDeletionRequest
from app.services.account_deletion_service import AccountDeletionService
from app.services.digilocker_service import DigiLockerService


@pytest.fixture
async def harness():
    runtime = get_settings()
    if runtime.app_env.value != "test" or any(
        urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1"}
        for url in (runtime.runtime_database_url, runtime.redis_url)
    ):
        raise RuntimeError("DigiLocker lifecycle tests require loopback-only test services")
    config = settings(redis_key_prefix="digilocker-tests:" + uuid4().hex)
    redis = Redis.from_url(runtime.redis_url, decode_responses=True)
    await redis.ping()
    ids = []
    async with async_session_factory() as session:
        for _ in range(2):
            user = User(
                email=f"dl-{uuid4()}@example.invalid",
                role="user",
                is_active=True,
                email_verified_at=datetime.now(UTC),
                password_hash=hash_password("TestOnly123!"),
            )
            session.add(user)
            await session.flush()
            ids.append(user.id)
        await session.commit()
    fake = provider(config)

    async def call(method, user_id=None, **kwargs):
        async with async_session_factory() as session:
            service = DigiLockerService(session, config, redis, provider=fake)
            if method == "callback":
                return await service.callback(**kwargs)
            return await getattr(service, method)(user_id or ids[0], **kwargs)

    async def connection(user_id=None):
        async with async_session_factory() as session:
            return await session.scalar(
                select(DigiLockerConnection).where(
                    DigiLockerConnection.user_id == (user_id or ids[0])
                )
            )

    async def start():
        response = await call("connect")
        return parse_qs(urlsplit(response["authorization_url"]).query)["state"][0]

    async def activate():
        state = await start()
        await call("callback", state=state, code="synthetic-code")
        return await connection()

    async def alter(**changes):
        async with async_session_factory() as session:
            row = await session.scalar(
                select(DigiLockerConnection).where(DigiLockerConnection.user_id == ids[0])
            )
            for key, value in changes.items():
                setattr(row, key, value)
            await session.commit()

    yield SimpleNamespace(
        config=config,
        redis=redis,
        ids=ids,
        fake=fake,
        call=call,
        connection=connection,
        start=start,
        activate=activate,
        alter=alter,
    )
    async with async_session_factory() as session:
        await session.execute(delete(User).where(User.id.in_(ids)))
        await session.commit()
    keys = [key async for key in redis.scan_iter(match=config.redis_key_prefix + ":*")]
    if keys:
        await redis.delete(*keys)
    await redis.aclose()


async def test_pkce_state_hash_ttl_single_use_and_supersession(harness):
    h = harness
    store = TransactionStore(h.redis, h.config)
    now = datetime.now(UTC)
    first = await store.create(h.ids[0], uuid4(), uuid4(), now)
    second = await store.create(h.ids[0], uuid4(), uuid4(), now)
    assert first.state != second.state
    assert len(second.state.get_secret_value()) == 43
    assert 43 <= len(second.verifier.get_secret_value()) <= 128
    assert (
        second.challenge
        == base64.urlsafe_b64encode(
            hashlib.sha256(second.verifier.get_secret_value().encode()).digest()
        )
        .rstrip(b"=")
        .decode()
    )
    keys = [key async for key in h.redis.scan_iter(match=h.config.redis_key_prefix + ":*")]
    assert len(keys) == 4  # Owner, current payload, and both bounded routing locators.
    assert all(second.state.get_secret_value() not in key for key in keys)
    assert all([0 < await h.redis.ttl(key) <= 600 for key in keys])
    with pytest.raises(StateError):
        await store.consume(first.state.get_secret_value(), now)
    results = await asyncio.gather(
        *[store.consume(second.state.get_secret_value(), now) for _ in range(2)],
        return_exceptions=True,
    )
    assert sum(isinstance(result, StateError) for result in results) == 1
    assert sum(getattr(result, "user_id", None) == h.ids[0] for result in results) == 1
    consumed = next(result for result in results if not isinstance(result, StateError))
    assert consumed.verifier == second.verifier


async def test_synthetic_stored_pkce_and_exact_staging_token_wire_contract(harness):
    h = harness
    callback = "https://staging-api.kairoid.com/api/v1/integrations/digilocker/callback"
    config = settings(
        digilocker_redirect_uri=callback,
        digilocker_authorize_url="https://digilocker.meripehchaan.gov.in/public/oauth2/2/authorize",
        digilocker_token_url="https://digilocker.meripehchaan.gov.in/public/oauth2/2/token",
    )
    store = TransactionStore(h.redis, h.config)
    now = datetime.now(UTC)
    tx = await store.create(h.ids[0], uuid4(), uuid4(), now)
    verifier = tx.verifier.get_secret_value()
    assert re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier)
    assert tx.challenge == base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    calls = []

    def handle(request):
        calls.append(request)
        assert request.method == "POST"
        assert str(request.url) == "https://digilocker.meripehchaan.gov.in/public/oauth2/2/token"
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        assert "authorization" not in request.headers
        body = parse_qs(request.content.decode(), keep_blank_values=True)
        assert body == {"code": ["synthetic-code"], "grant_type": ["authorization_code"],
                        "redirect_uri": [callback], "code_verifier": [verifier],
                        "client_id": [config.digilocker_client_id],
                        "client_secret": [config.digilocker_client_secret.get_secret_value()]}
        assert all(len(v) == 1 and v[0] and v[0] != "None" for v in body.values())
        return httpx.Response(200, json={"access_token": "synthetic-access",
                                       "token_type": "Bearer", "expires_in": 3600})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        wire = DigiLockerProvider(config, client=client)
        authorize = urlsplit(wire.build_authorization_url(
            state=tx.state.get_secret_value(), challenge=tx.challenge, now=now))
        assert authorize.scheme + "://" + authorize.netloc + authorize.path == (
            "https://digilocker.meripehchaan.gov.in/public/oauth2/2/authorize")
        auth = parse_qs(authorize.query)
        assert auth["dl_flow"] == ["signin"]
        assert not {"scope", "acr", "amr", "req_doctype", "prompt"} & auth.keys()
        assert auth["purpose"] == [config.digilocker_purpose]
        assert auth["service_name"] == [config.digilocker_service_name]
        assert auth["redirect_uri"] == [callback]
        assert auth["code_challenge"] == [tx.challenge]
        assert auth["code_challenge_method"] == ["S256"]
        consumed = await store.consume(tx.state.get_secret_value(), now)
        assert consumed.verifier.get_secret_value() == verifier
        await wire.exchange_authorization_code(
            SecretStr("synthetic-code"), consumed.verifier, now=now)
    assert len(calls) == 1


async def test_expired_and_unknown_state(harness):
    store = TransactionStore(harness.redis, harness.config)
    now = datetime.now(UTC)
    tx = await store.create(harness.ids[0], uuid4(), uuid4(), now)
    with pytest.raises(StateError) as exc:
        await store.consume(tx.state.get_secret_value(), now + timedelta(seconds=601))
    assert exc.value.category == "callback_expired"
    with pytest.raises(StateError):
        await store.consume(secrets.token_urlsafe(32), now)
    with pytest.raises(StateError):
        await store.consume("short", now)


async def test_connect_callback_encrypted_scoped_metadata_and_no_sensitive_logs(harness, caplog):
    h = harness
    caplog.set_level(logging.INFO, logger="app.services.digilocker_service")
    state = await h.start()
    assert (await h.call("status"))["status"] == "pending"
    result = await h.call("callback", state=state, code="synthetic-code")
    assert result == {"connection_state": "active"}
    row = await h.connection()
    secret_grant = h.fake.exchange_authorization_code.return_value
    persisted = json.dumps(
        {
            column: getattr(row, column)
            for column in ("encrypted_access_token", "encrypted_refresh_token", "granted_scopes")
        }
    )
    status = await h.call("status")
    assert status["connected"] is True
    for secret in [
        secret_grant.access_token.get_secret_value(),
        secret_grant.refresh_token.get_secret_value(),
        state,
        "synthetic-code",
    ]:
        assert secret not in persisted
        assert secret not in str(status)
        assert secret not in caplog.text
    assert (await h.call("status", h.ids[1]))["connected"] is False
    await h.call("disconnect", h.ids[1])
    assert (await h.call("status"))["connected"] is True
    with pytest.raises(ValidationAppError):
        await h.call("callback", state=state, code="synthetic-code")
    h.fake.exchange_authorization_code.assert_awaited_once()
    assert {record.message for record in caplog.records} >= {
        "digilocker_connect_started",
        "digilocker_connected",
    }


async def test_concurrent_callbacks_exchange_once(harness):
    h = harness
    state = await h.start()
    results = await asyncio.gather(
        *[h.call("callback", state=state, code="synthetic-code") for _ in range(2)],
        return_exceptions=True,
    )
    assert sum(isinstance(result, ValidationAppError) for result in results) == 1
    assert sum(result == {"connection_state": "active"} for result in results) == 1
    h.fake.exchange_authorization_code.assert_awaited_once()


@pytest.mark.parametrize("mode", ["denial", "missing_code", "both", "provider_failure"])
async def test_failed_callbacks_consume_state_and_store_no_tokens(harness, mode):
    h = harness
    state = await h.start()
    kwargs = {"state": state}
    if mode in {"denial", "both"}:
        kwargs["error"] = "access_denied"
    if mode in {"both", "provider_failure"}:
        kwargs["code"] = "synthetic-code"
    if mode == "provider_failure":
        h.fake.exchange_authorization_code.side_effect = ProviderError("provider_unavailable")
    with pytest.raises((ValidationAppError, ServiceUnavailableError)):
        await h.call("callback", **kwargs)
    row = await h.connection()
    assert row.status == "disconnected"
    assert row.encrypted_access_token is None and row.encrypted_refresh_token is None
    with pytest.raises(ValidationAppError):
        await h.call("callback", **kwargs)
    assert h.fake.exchange_authorization_code.await_count == (mode == "provider_failure")


async def test_superseded_or_disconnected_pending_callback_cannot_connect(harness):
    h = harness
    first = await h.start()
    second = await h.start()
    with pytest.raises(ValidationAppError):
        await h.call("callback", state=first, code="synthetic-code")
    await h.call("disconnect")
    with pytest.raises(ValidationAppError):
        await h.call("callback", state=second, code="synthetic-code")
    h.fake.exchange_authorization_code.assert_not_awaited()


async def test_database_attempt_fence_rejects_already_consumed_old_transaction(harness):
    h = harness
    first = await h.start()
    store = TransactionStore(h.redis, h.config)
    tx = await store.consume(first, datetime.now(UTC))
    await h.start()
    async with async_session_factory() as session:
        service = DigiLockerService(session, h.config, h.redis, provider=h.fake)
        service.store.consume = AsyncMock(return_value=tx)
        with pytest.raises(ValidationAppError):
            await service.callback(state=first, code="synthetic-code")
    h.fake.exchange_authorization_code.assert_not_awaited()


async def test_disabled_and_non_candidate_fail_closed(harness):
    h = harness
    h.config.digilocker_enabled = False
    with pytest.raises(ServiceUnavailableError) as exc:
        await h.start()
    assert exc.value.code == "digilocker_not_configured"
    h.config.digilocker_enabled = True
    async with async_session_factory() as session:
        user = await session.get(User, h.ids[0])
        user.role = "admin"
        await session.commit()
    with pytest.raises(ForbiddenError):
        await h.start()


async def test_bounded_repeated_connect_and_active_conflict(harness):
    h = harness
    await h.activate()
    with pytest.raises(ConflictError):
        await h.start()
    await h.call("disconnect")
    for _ in range(3):
        await h.start()
    from app.exceptions import RateLimitError

    with pytest.raises(RateLimitError):
        await h.start()
    keys = [key async for key in h.redis.scan_iter(match=h.config.redis_key_prefix + ":*")]
    assert len(keys) == 7  # Rate key, owner/payload, and four retained routing locators.


async def test_refresh_rotation_serialized_and_current_token_not_refreshed(harness):
    h = harness
    before = await h.activate()
    assert (
        await h.call("access_token") == h.fake.exchange_authorization_code.return_value.access_token
    )
    h.fake.refresh_access_token.assert_not_awaited()
    await h.alter(token_expires_at=datetime.now(UTC) - timedelta(seconds=1))
    results = await asyncio.gather(h.call("access_token"), h.call("access_token"))
    assert results == [h.fake.refresh_access_token.return_value.access_token] * 2
    h.fake.refresh_access_token.assert_awaited_once()
    after = await h.connection()
    assert after.encrypted_refresh_token != before.encrypted_refresh_token
    assert after.refreshed_at is not None


async def test_refresh_omitted_optional_values_preserved(harness):
    h = harness
    consent = datetime.now(UTC) + timedelta(days=10)
    h.fake.exchange_authorization_code.return_value = grant(consent=consent)
    before = await h.activate()
    h.fake.refresh_access_token.return_value = grant(refresh=False)
    from dataclasses import replace

    h.fake.refresh_access_token.return_value = replace(
        h.fake.refresh_access_token.return_value, scopes=None
    )
    await h.alter(token_expires_at=datetime.now(UTC))
    await h.call("access_token")
    after = await h.connection()
    assert after.encrypted_refresh_token == before.encrypted_refresh_token
    assert after.granted_scopes == before.granted_scopes
    assert after.consent_valid_until == before.consent_valid_until


@pytest.mark.parametrize("mode", ["invalid_grant", "no_refresh", "consent_expired", "bad_envelope"])
async def test_unusable_credentials_require_reconnect_and_are_erased(harness, mode):
    h = harness
    await h.activate()
    await h.alter(token_expires_at=datetime.now(UTC))
    if mode == "invalid_grant":
        h.fake.refresh_access_token.side_effect = ProviderError("invalid_grant")
    elif mode == "no_refresh":
        await h.alter(encrypted_refresh_token=None)
    elif mode == "consent_expired":
        await h.alter(consent_valid_until=datetime.now(UTC) - timedelta(seconds=1))
    else:
        await h.alter(encrypted_refresh_token={"not": "an envelope"})
    with pytest.raises(ValidationAppError) as exc:
        await h.call("access_token")
    assert exc.value.code == "digilocker_reconnect_required"
    row = await h.connection()
    assert row.status == "reconnect_required"
    assert row.encrypted_access_token is None and row.encrypted_refresh_token is None


async def test_refresh_provider_outage_preserves_ciphertext_and_fails_closed(harness):
    h = harness
    before = await h.activate()
    await h.alter(token_expires_at=datetime.now(UTC))
    h.fake.refresh_access_token.side_effect = ProviderError("provider_unavailable")
    with pytest.raises(ServiceUnavailableError):
        await h.call("access_token")
    assert (await h.connection()).encrypted_refresh_token == before.encrypted_refresh_token


@pytest.mark.parametrize("mode", ["normal", "offline", "disabled", "missing_key"])
async def test_disconnect_always_erases_local_tokens(harness, mode):
    h = harness
    await h.activate()
    if mode == "offline":
        h.fake.revoke_token.side_effect = ProviderError("provider_unavailable")
    if mode == "disabled":
        h.config.digilocker_enabled = False
    if mode == "missing_key":
        h.config.digilocker_token_encryption_keys = None
    await h.call("disconnect")
    row = await h.connection()
    assert row.status == "disconnected" and row.revoked_at is not None
    assert row.encrypted_access_token is None and row.encrypted_refresh_token is None
    assert row.granted_scopes == [] and row.consent_valid_until is None
    if mode in {"normal", "offline"}:
        assert h.fake.revoke_token.await_count == 2


async def test_redis_failure_is_closed_not_local_fallback(harness):
    h = harness
    async with async_session_factory() as session:
        redis = SimpleNamespace(eval=AsyncMock(side_effect=RedisConnectionError("private details")))
        service = DigiLockerService(session, h.config, redis, provider=h.fake)
        with pytest.raises(ServiceUnavailableError) as exc:
            await service.connect(h.ids[0])
        assert "private" not in str(exc.value)
    assert await h.connection() is None


@pytest.mark.parametrize("pending", [False, True])
async def test_local_account_deletion_purges_connection_and_ephemeral_state(harness, pending):
    h = harness
    if pending:
        state = await h.start()
    else:
        await h.activate()
        state = None
    store = TransactionStore(h.redis, h.config)
    owner_key = store._owner_key(store._routing_tag(h.ids[0]))
    assert await h.redis.exists(owner_key) == 1
    locators = [key async for key in h.redis.scan_iter(match=store.route_prefix + "*")]
    assert len(locators) == 1
    before_ttl = await h.redis.pttl(locators[0])
    async with async_session_factory() as session:
        await AccountDeletionService(session, h.config, h.redis).delete_candidate_account(
            h.ids[0], AccountDeletionRequest(confirm="DELETE", current_password="TestOnly123!")
        )
    assert await h.connection() is None
    keys = [key async for key in h.redis.scan_iter(match=store.prefix + "*")]
    assert keys == []
    assert 0 < await h.redis.pttl(locators[0]) <= before_ttl <= 600_000
    if state:
        with pytest.raises(ValidationAppError):
            await h.call("callback", state=state, code="synthetic-code")
    h.fake.revoke_token.assert_not_awaited()  # No live or queued provider work during deletion.


async def test_database_unique_owner_and_inactive_token_constraint(harness):
    h = harness
    await h.activate()
    async with async_session_factory() as session:
        session.add(DigiLockerConnection(user_id=h.ids[0], status="disconnected"))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
        session.add(
            DigiLockerConnection(
                user_id=h.ids[1],
                status="disconnected",
                encrypted_access_token={"invalid": "material"},
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
        count = await session.scalar(
            select(func.count())
            .select_from(DigiLockerConnection)
            .where(DigiLockerConnection.user_id.in_(h.ids))
        )
        assert count == 1


async def test_callback_commit_failure_rolls_back_and_revokes_unstored_grant(harness, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    h = harness
    state = await h.start()
    async with async_session_factory() as session:
        monkeypatch.setattr(session, "commit", AsyncMock(side_effect=SQLAlchemyError("private")))
        service = DigiLockerService(session, h.config, h.redis, provider=h.fake)
        with pytest.raises(ServiceUnavailableError):
            await service.callback(state=state, code="synthetic-code")
    row = await h.connection()
    assert row.status == "pending" and row.encrypted_access_token is None
    assert h.fake.revoke_token.await_count == 2
    with pytest.raises(ValidationAppError):
        await h.call("callback", state=state, code="synthetic-code")
    h.fake.exchange_authorization_code.assert_awaited_once()


async def test_expired_connection_status_and_reconnect_agree(harness):
    h = harness
    h.fake.exchange_authorization_code.return_value = grant(refresh=False)
    await h.activate()
    await h.alter(token_expires_at=datetime.now(UTC) - timedelta(seconds=1))
    assert (await h.call("status"))["status"] == "reconnect_required"
    assert await h.start()
    row = await h.connection()
    assert row.status == "pending" and row.encrypted_access_token is None


async def test_deleted_owner_rejects_consumed_callback_even_if_redis_cleanup_fails(harness):
    h = harness
    state = await h.start()
    tx = await TransactionStore(h.redis, h.config).consume(state, datetime.now(UTC))
    failing_redis = SimpleNamespace(
        get=AsyncMock(side_effect=RedisConnectionError("private")),
        eval=AsyncMock(side_effect=RedisConnectionError("private")),
    )
    async with async_session_factory() as session:
        await AccountDeletionService(session, h.config, failing_redis).delete_candidate_account(
            h.ids[0], AccountDeletionRequest(confirm="DELETE", current_password="TestOnly123!")
        )
    async with async_session_factory() as session:
        service = DigiLockerService(session, h.config, h.redis, provider=h.fake)
        service.store.consume = AsyncMock(return_value=tx)
        with pytest.raises(ValidationAppError):
            await service.callback(state=state, code="synthetic-code")
    h.fake.exchange_authorization_code.assert_not_awaited()
    assert await h.connection() is None


async def test_account_deletion_failure_rolls_back_connection_purge(harness, monkeypatch):
    h = harness
    before = await h.activate()
    async with async_session_factory() as session:
        service = AccountDeletionService(session, h.config, h.redis)
        monkeypatch.setattr(
            service,
            "_purge_candidate_exclusive_rows",
            AsyncMock(side_effect=RuntimeError("synthetic failure")),
        )
        with pytest.raises(ServiceUnavailableError):
            await service.delete_candidate_account(
                h.ids[0], AccountDeletionRequest(confirm="DELETE", current_password="TestOnly123!")
            )
    after = await h.connection()
    assert after.encrypted_access_token == before.encrypted_access_token
    assert (await h.call("status"))["connected"] is True


async def test_refresh_reencrypts_with_current_active_key(harness):
    from pydantic import SecretStr

    h = harness
    before = await h.activate()
    keys = json.loads(h.config.digilocker_token_encryption_keys.get_secret_value())
    keys["test-v2"] = base64.b64encode(secrets.token_bytes(32)).decode()
    h.config.digilocker_token_encryption_keys = SecretStr(json.dumps(keys))
    h.config.digilocker_token_encryption_active_key_id = "test-v2"
    await h.alter(token_expires_at=datetime.now(UTC))
    await h.call("access_token")
    after = await h.connection()
    assert before.encrypted_access_token["key_id"] == "test-v1"
    assert after.encrypted_access_token["key_id"] == "test-v2"
    assert after.encrypted_refresh_token["key_id"] == "test-v2"


async def test_concurrent_connects_leave_one_current_attempt(harness):
    h = harness
    states = await asyncio.gather(h.start(), h.start())
    store = TransactionStore(h.redis, h.config)
    results = await asyncio.gather(
        *(store.consume(state, datetime.now(UTC)) for state in states),
        return_exceptions=True,
    )
    assert sum(isinstance(result, StateError) for result in results) == 1
    current = next(result for result in results if not isinstance(result, StateError))
    assert current.attempt_id == (await h.connection()).pending_attempt_id
    async with async_session_factory() as session:
        service = DigiLockerService(session, h.config, h.redis, provider=h.fake)
        service.store.consume = AsyncMock(return_value=current)
        assert await service.callback(state="synthetic", code="synthetic-code") == {
            "connection_state": "active"
        }
    h.fake.exchange_authorization_code.assert_awaited_once()


@pytest.mark.parametrize(
    "mode", ["nx_conflict", "pointer_read", "create_rejected", "create_timeout"]
)
async def test_locator_storage_failure_rolls_back_pending_attempt(harness, monkeypatch, mode):
    h = harness
    original_eval = h.redis.eval

    if mode == "nx_conflict":
        monkeypatch.setattr(h.redis, "set", AsyncMock(return_value=None))
    elif mode == "pointer_read":
        monkeypatch.setattr(h.redis, "get", AsyncMock(side_effect=RedisConnectionError("private")))
    else:
        from app.integrations.digilocker.transactions import _CREATE

        async def fail_create(script, *args):
            if script == _CREATE:
                if mode == "create_timeout":
                    await original_eval(script, *args)
                    raise RedisConnectionError("private")
                return 0
            return await original_eval(script, *args)

        monkeypatch.setattr(h.redis, "eval", fail_create)
    with pytest.raises(ServiceUnavailableError) as exc:
        await h.start()
    assert exc.value.code == "digilocker_storage_unavailable"
    assert "private" not in str(exc.value)
    assert await h.connection() is None
    h.fake.exchange_authorization_code.assert_not_awaited()


async def test_callback_locator_outage_is_sanitized_without_provider_call(harness, monkeypatch):
    h = harness
    state = await h.start()
    monkeypatch.setattr(h.redis, "get", AsyncMock(side_effect=RedisConnectionError("private")))
    with pytest.raises(ServiceUnavailableError) as exc:
        await h.call("callback", state=state, code="synthetic-code")
    assert exc.value.code == "digilocker_storage_unavailable"
    assert "private" not in str(exc.value)
    assert (await h.connection()).status == "pending"
    h.fake.exchange_authorization_code.assert_not_awaited()


async def test_document_reads_preserve_connection_and_enforce_database_owner(harness):
    from app.exceptions import NotFoundError
    from app.integrations.digilocker.documents import RetrievedDocument, normalize_items
    from app.services.digilocker_document_service import DigiLockerDocumentService

    h = harness
    before = await h.activate()
    docs = SimpleNamespace(
        issued=AsyncMock(
            return_value=normalize_items(
                {
                    "items": [
                        {
                            "name": "Synthetic PAN",
                            "type": "file",
                            "doctype": "PANCR",
                            "uri": "in.test-PANCR-SYNTHETIC",
                            "issuerid": "in.test",
                            "issuer": "Synthetic issuer",
                            "mime": "application/pdf",
                        }
                    ]
                }
            )
        ),
        retrieve=AsyncMock(return_value=RetrievedDocument(b"synthetic", "application/pdf")),
    )
    async with async_session_factory() as session:
        service = DigiLockerDocumentService(session, h.config, h.redis, documents=docs)
        listing = await service.issued(h.ids[0])
        reference = listing["items"][0]["reference"]
        assert (await service.retrieve(h.ids[0], reference))["integrity"] == "verified"
        with pytest.raises(ValidationAppError):
            await service.retrieve(h.ids[1], reference)
    after = await h.connection()
    assert after.encrypted_access_token == before.encrypted_access_token
    assert after.encrypted_refresh_token == before.encrypted_refresh_token
    assert after.status == before.status == "active"
    assert after.refreshed_at == before.refreshed_at
    assert after.token_expires_at == before.token_expires_at
    h.fake.refresh_access_token.assert_not_awaited()
    h.fake.revoke_token.assert_not_awaited()
    docs.retrieve.assert_awaited_once()
    # The same issued reference must also fail for an otherwise-active second account.
    state = (await h.call("connect", h.ids[1]))["authorization_url"]
    await h.call(
        "callback", state=parse_qs(urlsplit(state).query)["state"][0], code="synthetic-second-code"
    )
    async with async_session_factory() as session:
        service = DigiLockerDocumentService(session, h.config, h.redis, documents=docs)
        with pytest.raises(NotFoundError):
            await service.retrieve(h.ids[1], reference)
    docs.retrieve.assert_awaited_once()
