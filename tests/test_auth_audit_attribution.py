from __future__ import annotations

import asyncio
import io
import json
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.auth.service import AuthService
from app.config import get_settings
from app.exceptions import UnauthorizedError
from app.logging import auth_audit as audit
from app.middleware.request_context import RequestContextMiddleware
from app.models.refresh_token import RefreshToken
from app.services.account_settings_service import AccountSettingsService


class Session:
    def __init__(self):
        self.added = []
        self.commit = AsyncMock()
        self.scalar = AsyncMock()

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        for row in self.added:
            if row.id is None:
                row.id = uuid4()


@pytest.fixture
def captured():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(audit.AuthAuditFormatter("test"))
    old_handlers, old_level = audit.logger.handlers[:], audit.logger.level
    audit.logger.handlers[:] = [handler]
    audit.logger.setLevel(logging.INFO)
    yield stream
    audit.logger.handlers[:] = old_handlers
    audit.logger.setLevel(old_level)


def events(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def service():
    db = Session()
    user = SimpleNamespace(
        id=uuid4(),
        role="user",
        is_active=True,
        deleted_at=None,
        email_verified_at=datetime.now(UTC),
    )
    row = RefreshToken(
        id=uuid4(),
        user_id=user.id,
        family_id=uuid4(),
        token_hash="PRIVATE_TOKEN_HASH",
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    auth = AuthService(db, get_settings(), SimpleNamespace())
    auth._users = SimpleNamespace(get_by_id=AsyncMock(return_value=user))
    auth._refresh = SimpleNamespace(
        get_by_hash_any=AsyncMock(return_value=row), revoke=AsyncMock(), revoke_family=AsyncMock()
    )
    return auth, db, user, row


async def test_logout_committed_and_idempotent_events(captured):
    auth, db, user, row = service()
    await auth.logout(SimpleNamespace(refresh_token="PRIVATE_REFRESH_TOKEN"))
    records = events(captured)
    assert [r["event"] for r in records] == ["AUTH_LOGOUT_REQUEST", "AUTH_LOGOUT_SESSION_REVOKED"]
    assert all(
        r["user_id"] == str(user.id)
        and r["session_id"] == str(row.id)
        and r["family_id"] == str(row.family_id)
        for r in records
    )
    db.commit.assert_awaited_once()
    auth._refresh.revoke.assert_awaited_once_with(row.id)
    row.revoked_at = datetime.now(UTC)
    await auth.logout(SimpleNamespace(refresh_token="PRIVATE_REFRESH_TOKEN"))
    assert events(captured)[-1]["event"] == "AUTH_LOGOUT_REQUEST"
    assert len(events(captured)) == 3
    assert "PRIVATE" not in captured.getvalue()


async def test_unknown_logout_is_not_claimed_as_revocation(captured):
    auth, db, _, _ = service()
    auth._refresh.get_by_hash_any.return_value = None
    await auth.logout(SimpleNamespace(refresh_token="PRIVATE_REFRESH_TOKEN"))
    assert [r["event"] for r in events(captured)] == ["AUTH_LOGOUT_REQUEST"]
    assert events(captured)[0]["user_id"] is None
    db.commit.assert_not_awaited()


async def test_failed_commit_does_not_claim_logout_revocation(captured):
    auth, db, _, _ = service()
    db.commit.side_effect = RuntimeError("PRIVATE_DB_DETAILS")
    with pytest.raises(RuntimeError):
        await auth.logout(SimpleNamespace(refresh_token="PRIVATE_REFRESH_TOKEN"))
    assert [r["event"] for r in events(captured)] == ["AUTH_LOGOUT_REQUEST"]
    assert "PRIVATE" not in captured.getvalue()


async def test_rotation_records_predecessor_and_successor_without_tokens(captured):
    auth, db, user, row = service()
    result = await auth.refresh(SimpleNamespace(refresh_token="PRIVATE_REFRESH_TOKEN"))
    (record,) = events(captured)
    assert record["event"] == "AUTH_REFRESH_ROTATE"
    assert record["user_id"] == str(user.id)
    assert record["session_id"] == str(row.id)
    assert record["family_id"] == str(row.family_id)
    assert record["successor_session_id"] == str(db.added[0].id)
    assert db.added[0].family_id == row.family_id
    for value in (
        result.access_token,
        result.refresh_token,
        row.token_hash,
        db.added[0].token_hash,
    ):
        assert value not in captured.getvalue()
    db.commit.assert_awaited_once()


async def test_family_reuse_is_distinct_and_keeps_401(captured):
    auth, db, user, row = service()
    row.revoked_at = datetime.now(UTC)
    with pytest.raises(UnauthorizedError, match="Refresh token reused"):
        await auth.refresh(SimpleNamespace(refresh_token="PRIVATE_REFRESH_TOKEN"))
    (record,) = events(captured)
    assert record["event"] == "AUTH_REFRESH_FAMILY_REVOKE"
    assert record["user_id"] == str(user.id) and record["family_id"] == str(row.family_id)
    auth._refresh.revoke_family.assert_awaited_once_with(row.family_id)
    db.commit.assert_awaited_once()
    assert db.added == []


@pytest.mark.parametrize("exclude_current", [False, True])
async def test_revoke_all_is_distinct_and_preserves_current_family(captured, exclude_current):
    _, db, user, row = service()
    account = AccountSettingsService(db, get_settings())
    account._users = SimpleNamespace(get_by_id=AsyncMock(return_value=user))
    account._refresh = SimpleNamespace(
        revoke_all_for_user=AsyncMock(), revoke_all_for_user_except_family=AsyncMock()
    )
    excluded = row.family_id if exclude_current else None
    await account.revoke_all_sessions(user.id, excluded)
    (record,) = events(captured)
    assert record["event"] == "AUTH_SESSION_REVOKE_ALL"
    assert record["user_id"] == str(user.id)
    assert record["excluded_family_id"] == (str(excluded) if excluded else None)
    if exclude_current:
        account._refresh.revoke_all_for_user_except_family.assert_awaited_once_with(
            user.id, excluded
        )
    else:
        account._refresh.revoke_all_for_user.assert_awaited_once_with(user.id)


async def test_single_session_revoke_has_target(captured):
    _, db, user, row = service()
    account = AccountSettingsService(db, get_settings())
    account._users = SimpleNamespace(get_by_id=AsyncMock(return_value=user))
    account._refresh = SimpleNamespace(revoke=AsyncMock())
    db.scalar.return_value = row
    await account.revoke_session(user.id, row.id, uuid4())
    (record,) = events(captured)
    assert record["event"] == "AUTH_SESSION_REVOKE"
    assert record["user_id"] == str(user.id) and record["session_id"] == str(row.id)


@pytest.mark.parametrize(
    "agent,expected",
    [
        ("Mozilla/5.0 (Linux; Android 15; phone; wv) SECRET", "android_webview"),
        ("Mozilla/5.0 (Linux; Android 15) Chrome/1 SECRET", "android_browser"),
        ("Mozilla/5.0 (iPhone) SECRET", "ios_browser"),
        ("Mozilla/5.0 Chrome/1 SECRET", "browser"),
        ("SECRET", "other"),
    ],
)
def test_client_classification_never_retains_agent(captured, agent, expected):
    request = uuid4()
    token = audit.begin_auth_audit(str(request), str(request), agent)
    audit.auth_audit("AUTH_LOGOUT_REQUEST", user_id=uuid4())
    audit.finish_auth_audit(token, endpoint="/api/v1/auth/logout", status=204)
    (record,) = events(captured)
    assert record["client_class"] == expected
    assert record["request_id"] == str(request)
    assert record["http_status"] == 204
    assert "SECRET" not in captured.getvalue()
    assert audit._capture.get() is None


def test_formatter_drops_arbitrary_sensitive_extras():
    record = logging.LogRecord("audit", 20, "file", 1, "PASSWORD", (), None)
    record.audit = {
        "event": "AUTH_LOGOUT_REQUEST",
        "user_id": "EMAIL@example.test",
        "request_id": "TOKEN",
        "endpoint": "/api/v1/auth/logout?token=TOKEN",
        "client_class": "RAW_USER_AGENT",
        "refresh_token": "TOKEN",
        "token_hash": "HASH",
        "password": "PASSWORD",
        "phone": "PHONE",
    }
    record.access_token = "ACCESS"
    record.exc_text = "SECRET_EXCEPTION"
    rendered = audit.AuthAuditFormatter("test").format(record)
    assert not any(
        x in rendered
        for x in (
            "PASSWORD",
            "TOKEN",
            "HASH",
            "PHONE",
            "EMAIL",
            "ACCESS",
            "RAW_USER_AGENT",
            "SECRET_EXCEPTION",
        )
    )


async def test_actual_middleware_status_and_concurrent_request_isolation(captured):
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    targets = {"first": uuid4(), "second": uuid4()}

    @app.post("/api/v1/audit-test/{key}", status_code=202)
    async def endpoint(key: str):
        await asyncio.sleep(0)
        audit.auth_audit("AUTH_LOGOUT_REQUEST", user_id=targets[key])
        await asyncio.sleep(0)
        return {"ok": True}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        request_ids = [str(uuid4()), str(uuid4())]
        responses = await asyncio.gather(
            *[
                client.post("/api/v1/audit-test/" + key, headers={"X-Request-ID": request_id})
                for key, request_id in zip(targets, request_ids, strict=True)
            ]
        )
    assert all(response.status_code == 202 for response in responses)
    records = events(captured)
    assert len(records) == 2
    for key, request_id in zip(targets, request_ids, strict=True):
        (record,) = [r for r in records if r["request_id"] == request_id]
        assert record["user_id"] == str(targets[key])
        assert record["endpoint"] == "/api/v1/audit-test/{key}"
        assert record["http_status"] == 202


async def test_logging_failure_does_not_change_logout_behavior(monkeypatch):
    auth, db, _, row = service()

    def fail(*args, **kwargs):
        raise RuntimeError("logging failed")

    monkeypatch.setattr(audit.logger, "info", fail)
    await auth.logout(SimpleNamespace(refresh_token="PRIVATE_REFRESH_TOKEN"))
    auth._refresh.revoke.assert_awaited_once_with(row.id)
    db.commit.assert_awaited_once()


@pytest.mark.parametrize("revoked", [False, True])
async def test_failed_refresh_commit_does_not_claim_effect(captured, revoked):
    auth, db, _, row = service()
    if revoked:
        row.revoked_at = datetime.now(UTC)
    db.commit.side_effect = RuntimeError("PRIVATE_DB_DETAILS")
    with pytest.raises(RuntimeError):
        await auth.refresh(SimpleNamespace(refresh_token="PRIVATE_REFRESH_TOKEN"))
    assert events(captured) == []


def test_bounded_capture_and_failure_cleanup(monkeypatch, captured):
    token = audit.begin_auth_audit("untrusted-secret", "untrusted-secret", "private-agent")
    for _ in range(20):
        audit.auth_audit("AUTH_LOGOUT_REQUEST", user_id=uuid4())
    audit.finish_auth_audit(token, endpoint="/api/v1/auth/logout", status=500)
    assert len(events(captured)) == 16
    assert all(r["http_status"] == 500 and r["request_id"] is None for r in events(captured))
    assert audit._capture.get() is None
    token = audit.begin_auth_audit(None, None, "")
    audit.auth_audit("AUTH_LOGOUT_REQUEST")
    monkeypatch.setattr(
        audit.logger, "info", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError())
    )
    audit.finish_auth_audit(token, endpoint="/api/v1/auth/logout", status=500)
    assert audit._capture.get() is None
