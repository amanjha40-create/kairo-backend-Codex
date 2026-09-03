"""Privacy, state, and route coverage for interrupted Candidate signup recovery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.services import get_auth_service
from app.auth.service import AuthService
from app.config import get_settings
from app.core.constants import SignupKind
from app.exceptions import NotFoundError
from app.infrastructure.redis.deps import get_redis
from app.main import app
from app.schemas.auth import (
    SignupSessionNextStep,
    SignupSessionRecoveryResponse,
    SignupSessionRecoveryState,
)

SENTINEL_EMAIL = "founder.qa@example.test"
SENTINEL_PHONE = "+919876543210"
SENTINEL_PASSWORD_HASH = "sentinel-password-hash-must-not-leak"
SENTINEL_OTP = "849201"
SENTINEL_PROVIDER_SECRET = "sentinel-provider-secret-must-not-leak"


def _pending_signup(
    *,
    email_verified: bool = False,
    phone_verified: bool = False,
    completed: bool = False,
    expired: bool = False,
    signup_kind: SignupKind = SignupKind.CANDIDATE,
) -> SimpleNamespace:
    now = datetime.now(tz=UTC)
    return SimpleNamespace(
        id=uuid4(),
        signup_kind=signup_kind.value,
        email=SENTINEL_EMAIL,
        phone=SENTINEL_PHONE,
        password_hash=SENTINEL_PASSWORD_HASH,
        expires_at=now - timedelta(minutes=1) if expired else now + timedelta(hours=12),
        email_verified_at=now - timedelta(minutes=5) if email_verified else None,
        phone_verified_at=now - timedelta(minutes=4) if phone_verified else None,
        email_otp_sent_count=1,
        email_verify_attempt_count=0,
        email_last_otp_sent_at=now - timedelta(seconds=5),
        phone_otp_sent_count=1,
        phone_verify_attempt_count=0,
        phone_last_otp_sent_at=now - timedelta(seconds=4),
        completed_user_id=uuid4() if completed else None,
        completed_at=now - timedelta(minutes=1) if completed else None,
    )


def _service_for(row: SimpleNamespace | None) -> tuple[AuthService, SimpleNamespace]:
    service = AuthService.__new__(AuthService)
    pending = SimpleNamespace(
        rows=[] if row is None else [row],
        get_by_id=AsyncMock(return_value=row),
        delete_by_id=AsyncMock(),
    )
    session = SimpleNamespace(
        add=Mock(),
        flush=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
        delete=AsyncMock(),
        execute=AsyncMock(),
    )
    otp = SimpleNamespace(
        clear=AsyncMock(),
        clear_all=AsyncMock(),
        store_otp=AsyncMock(),
        enforce_send_rate=AsyncMock(),
    )
    users = SimpleNamespace(rows=[], get_by_id=AsyncMock(), get_by_email=AsyncMock())

    service._pending = pending  # type: ignore[attr-defined]
    service._session = session  # type: ignore[attr-defined]
    service._otp = otp  # type: ignore[attr-defined]
    service._users = users  # type: ignore[attr-defined]
    service._settings = SimpleNamespace(signup_otp_resend_cooldown_seconds=30)  # type: ignore[attr-defined]
    return service, SimpleNamespace(pending=pending, session=session, otp=otp, users=users)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("row", "state", "next_step"),
    (
        (
            _pending_signup(),
            SignupSessionRecoveryState.VALID,
            SignupSessionNextStep.VERIFY_EMAIL,
        ),
        (
            _pending_signup(email_verified=True),
            SignupSessionRecoveryState.VALID,
            SignupSessionNextStep.VERIFY_PHONE,
        ),
        (
            _pending_signup(email_verified=True, phone_verified=True),
            SignupSessionRecoveryState.VALID,
            SignupSessionNextStep.COMPLETE_SIGNUP,
        ),
        (
            _pending_signup(email_verified=True, phone_verified=True, completed=True, expired=True),
            SignupSessionRecoveryState.COMPLETED,
            SignupSessionNextStep.COMPLETED,
        ),
        (
            _pending_signup(expired=True),
            SignupSessionRecoveryState.EXPIRED,
            None,
        ),
    ),
)
async def test_recovery_projects_authoritative_state_without_mutation(
    row: SimpleNamespace,
    state: SignupSessionRecoveryState,
    next_step: SignupSessionNextStep | None,
) -> None:
    service, dependencies = _service_for(row)
    original_row = vars(row).copy()
    pending_count = len(dependencies.pending.rows)
    user_count = len(dependencies.users.rows)

    first = await service.recover_signup_session(row.id)
    second = await service.recover_signup_session(row.id)

    assert first == second
    assert first.state == state
    assert first.next_step == next_step
    assert first.email_masked == "f********a@example.test"
    assert first.phone_masked == "+91******3210"
    assert first.email_verified is (row.email_verified_at is not None)
    assert first.phone_verified is (row.phone_verified_at is not None)
    assert vars(row) == original_row
    assert len(dependencies.pending.rows) == pending_count
    assert len(dependencies.users.rows) == user_count
    dependencies.session.add.assert_not_called()
    dependencies.session.flush.assert_not_awaited()
    dependencies.session.commit.assert_not_awaited()
    dependencies.session.rollback.assert_not_awaited()
    dependencies.session.delete.assert_not_awaited()
    dependencies.session.execute.assert_not_awaited()
    dependencies.pending.delete_by_id.assert_not_awaited()
    dependencies.otp.clear.assert_not_awaited()
    dependencies.otp.clear_all.assert_not_awaited()
    dependencies.otp.store_otp.assert_not_awaited()
    dependencies.otp.enforce_send_rate.assert_not_awaited()
    dependencies.users.get_by_id.assert_not_awaited()
    dependencies.users.get_by_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_returns_fixed_authoritative_resend_timestamps() -> None:
    row = _pending_signup(email_verified=True)
    service, _ = _service_for(row)

    response = await service.recover_signup_session(row.id)

    assert response.email_resend_available_at is None
    assert response.phone_resend_available_at == row.phone_last_otp_sent_at + timedelta(seconds=30)


@pytest.mark.asyncio
async def test_recovery_hides_unknown_and_non_candidate_sessions() -> None:
    missing_service, _ = _service_for(None)
    with pytest.raises(NotFoundError, match="Signup session not found"):
        await missing_service.recover_signup_session(uuid4())

    organization = _pending_signup(signup_kind=SignupKind.ORGANIZATION)
    organization_service, _ = _service_for(organization)
    with pytest.raises(NotFoundError, match="Signup session not found"):
        await organization_service.recover_signup_session(organization.id)


@pytest.mark.asyncio
async def test_recovery_response_contains_no_secrets_or_full_contacts() -> None:
    row = _pending_signup()
    service, _ = _service_for(row)

    response = await service.recover_signup_session(row.id)
    serialized = response.model_dump_json()

    for sentinel in (
        SENTINEL_EMAIL,
        SENTINEL_PHONE,
        SENTINEL_PASSWORD_HASH,
        SENTINEL_OTP,
        SENTINEL_PROVIDER_SECRET,
        str(row.id),
    ):
        assert sentinel not in serialized

    assert response.email_masked == "f********a@example.test"
    assert response.phone_masked == "+91******3210"


class _RouteAuthService:
    def __init__(self, response: SignupSessionRecoveryResponse) -> None:
        self.response = response
        self.requested_session_ids: list[UUID] = []

    async def recover_signup_session(
        self, signup_session_id: UUID
    ) -> SignupSessionRecoveryResponse:
        self.requested_session_ids.append(signup_session_id)
        return self.response


class _MissingRouteAuthService:
    async def recover_signup_session(self, _: UUID) -> SignupSessionRecoveryResponse:
        raise NotFoundError("Signup session not found")


class _CountingRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def eval(self, _: str, __: int, key: str, ___: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def ttl(self, _: str) -> int:
        return 60


def _route_response() -> SignupSessionRecoveryResponse:
    now = datetime.now(tz=UTC)
    return SignupSessionRecoveryResponse(
        state=SignupSessionRecoveryState.VALID,
        email_masked="f********a@example.test",
        phone_masked="+91******3210",
        email_verified=False,
        phone_verified=False,
        next_step=SignupSessionNextStep.VERIFY_EMAIL,
        expires_at=now + timedelta(hours=12),
        email_resend_available_at=now + timedelta(seconds=25),
        phone_resend_available_at=None,
    )


def _install_route_overrides(fake: _RouteAuthService, redis: _CountingRedis) -> None:
    settings = SimpleNamespace(
        signup_recovery_rate_limit_max_requests=30,
        signup_recovery_rate_limit_window_seconds=60,
    )
    app.dependency_overrides[get_auth_service] = lambda: fake
    app.dependency_overrides[get_redis] = lambda: redis
    app.dependency_overrides[get_settings] = lambda: settings


@pytest.mark.asyncio
async def test_route_uses_header_credential_and_returns_no_store_projection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session_id = uuid4()
    fake = _RouteAuthService(_route_response())
    _install_route_overrides(fake, _CountingRedis())

    try:
        with caplog.at_level("INFO"):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/v1/auth/signup/session",
                    headers={"X-Signup-Session-ID": str(session_id)},
                )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert fake.requested_session_ids == [session_id]
    assert response.json()["next_step"] == "verify_email"
    assert "signup_session_id" not in response.json()
    assert "no-store" in response.headers["cache-control"]
    assert str(session_id) not in caplog.text


@pytest.mark.asyncio
async def test_route_returns_privacy_safe_404_for_unknown_session() -> None:
    app.dependency_overrides[get_auth_service] = lambda: _MissingRouteAuthService()
    app.dependency_overrides[get_redis] = lambda: _CountingRedis()
    app.dependency_overrides[get_settings] = lambda: SimpleNamespace(
        signup_recovery_rate_limit_max_requests=30,
        signup_recovery_rate_limit_window_seconds=60,
    )

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/auth/signup/session",
                headers={"X-Signup-Session-ID": str(uuid4())},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Signup session not found"}
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("header", (None, "not-a-uuid"))
async def test_route_rejects_missing_or_malformed_recovery_credential(
    header: str | None,
) -> None:
    fake = _RouteAuthService(_route_response())
    _install_route_overrides(fake, _CountingRedis())
    headers = {} if header is None else {"X-Signup-Session-ID": header}

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/auth/signup/session", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert fake.requested_session_ids == []


@pytest.mark.asyncio
async def test_route_has_distinct_thirty_per_minute_rate_limit() -> None:
    session_id = uuid4()
    fake = _RouteAuthService(_route_response())
    redis = _CountingRedis()
    _install_route_overrides(fake, redis)

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            responses = [
                await client.get(
                    "/api/v1/auth/signup/session",
                    headers={"X-Signup-Session-ID": str(session_id)},
                )
                for _ in range(31)
            ]
    finally:
        app.dependency_overrides.clear()

    assert all(response.status_code == 200 for response in responses[:30])
    assert responses[30].status_code == 429
    assert responses[30].headers["retry-after"] == "60"
    assert len(fake.requested_session_ids) == 30


def test_openapi_documents_privacy_safe_pre_account_contract() -> None:
    app.openapi_schema = None
    operation = app.openapi()["paths"]["/api/v1/auth/signup/session"]["get"]

    header = next(
        parameter
        for parameter in operation["parameters"]
        if parameter["name"] == "X-Signup-Session-ID"
    )
    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]

    assert header["in"] == "header"
    assert header["required"] is True
    assert response_schema["$ref"].endswith("/SignupSessionRecoveryResponse")
    assert operation.get("security") in (None, [])
    assert "masked contacts only" in operation["description"]
    assert {"404", "422", "429"}.issubset(operation["responses"])

    recovery_schema = app.openapi()["components"]["schemas"]["SignupSessionRecoveryResponse"]
    assert set(recovery_schema["properties"]) == {
        "state",
        "email_masked",
        "phone_masked",
        "email_verified",
        "phone_verified",
        "next_step",
        "expires_at",
        "email_resend_available_at",
        "phone_resend_available_at",
    }
