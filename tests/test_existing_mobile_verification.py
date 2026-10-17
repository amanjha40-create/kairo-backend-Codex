"""Synthetic recovery certification; delivery is always mocked, Redis is local."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from redis.asyncio import Redis

from app.auth.mobile_verification import MobileVerificationService
from app.auth.signup_otp import SignupOtpStore
from app.config import Settings
from app.exceptions import ForbiddenError, RateLimitError, UnauthorizedError


@pytest.fixture
async def recovery(monkeypatch):
    import os

    settings = Settings(
        phone_otp_backend="msg91",
        msg91_auth_key="synthetic-secret",
        msg91_template_id="synthetic-template",
    )
    redis = Redis.from_url(os.environ["REDIS_URL"])
    user = SimpleNamespace(
        id=uuid4(),
        role="user",
        email_verified_at=datetime.now(UTC),
        phone_verified_at=None,
        phone="+919876543210",
        full_name="Synthetic Candidate",
        headline="Engineer",
        current_role="Engineer",
        industry="Technology",
        years_of_experience=2,
        employment_onboarding_completed_at=None,
    )
    session = AsyncMock()
    provider = SimpleNamespace(send_signup_otp=AsyncMock(), verify_signup_otp=AsyncMock())
    service = MobileVerificationService(session, settings, redis, None, provider)
    scope = "existing_mobile_test_" + uuid4().hex
    service.otp = SignupOtpStore(redis, settings, scope=scope)
    monkeypatch.setattr(
        "app.auth.mobile_verification.lock_private_owner", AsyncMock(return_value=user)
    )
    # Deterministic fixtures are restricted to the test process.
    codes = iter(["134679", "246810", "345678", "456789", "567890", "678901"])
    monkeypatch.setattr("app.auth.mobile_verification.generate_otp_code", lambda: next(codes))
    yield service, user, redis, provider
    async for key in redis.scan_iter(match=f"*{scope}*"):
        await redis.delete(key)
    await redis.aclose()


async def remove_cooldown(service, user, redis):
    key = service.otp._keys.rate_limit(
        bucket=f"{service.otp._scope}_otp_cooldown", identifier=str(user.id)
    )
    await redis.delete(key)


@pytest.mark.asyncio
async def test_request_verify_updates_canonical_bootstrap(recovery):
    from app.services.passport_engine_service import PassportEngineService

    service, user, redis, provider = recovery
    result = await service.request(user.id)
    assert result.state == "code_sent" and result.expires_in_seconds == 300
    assert result.resend_after_seconds == 30 and user.phone_verified_at is None
    assert "134679" not in result.model_dump_json() and user.phone not in result.model_dump_json()
    stored = await redis.get(service.otp._otp_key(user.id, "phone"))
    assert b"134679" not in stored
    state = await service.otp.get_provider_state(user.id, "phone")
    assert user.phone not in str(state)
    assert (await service.verify(user.id, "134679")).phone_verified
    assert user.phone_verified_at is not None
    provider.verify_signup_otp.assert_awaited_once_with(to_phone=user.phone, code="134679")
    engine = PassportEngineService.__new__(PassportEngineService)
    engine._get_user = AsyncMock(return_value=user)
    status = await engine.get_onboarding_status(user.id)
    assert status.email_verified and status.phone_verified
    assert status.current_step != "verify_identity"
    assert await service.otp.get_provider_state(user.id, "phone") is None
    assert (await service.verify(user.id, "134679")).state == "verified"
    assert provider.verify_signup_otp.await_count == 1  # Replay never revalidates.


@pytest.mark.asyncio
async def test_wrong_expired_reused_and_attempt_cap(recovery):
    service, user, redis, provider = recovery
    await service.request(user.id)
    for _ in range(5):
        with pytest.raises(UnauthorizedError):
            await service.verify(user.id, "999999")
    with pytest.raises(RateLimitError):
        await service.verify(user.id, "134679")
    assert user.phone_verified_at is None
    provider.verify_signup_otp.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_metadata_and_redis_otp(recovery):
    service, user, redis, provider = recovery
    await service.request(user.id)
    state = await service.otp.get_provider_state(user.id, "phone")
    state["expires_at"] = 1
    await service.otp.store_provider_state(user.id, "phone", state)
    with pytest.raises(UnauthorizedError):
        await service.verify(user.id, "134679")
    provider.verify_signup_otp.assert_not_awaited()
    await remove_cooldown(service, user, redis)
    await service.request(user.id)
    await redis.delete(service.otp._otp_key(user.id, "phone"))
    with pytest.raises(UnauthorizedError):
        await service.verify(user.id, "246810")


@pytest.mark.asyncio
async def test_resend_invalidates_old_and_preserves_attempt_budget(recovery):
    service, user, redis, provider = recovery
    await service.request(user.id)
    with pytest.raises(RateLimitError):
        await service.request(user.id)
    await remove_cooldown(service, user, redis)
    await service.request(user.id)
    with pytest.raises(UnauthorizedError):
        await service.verify(user.id, "134679")
    assert (await service.verify(user.id, "246810")).phone_verified
    assert provider.send_signup_otp.await_count == 2


@pytest.mark.asyncio
async def test_resend_random_collision_does_not_reissue_prior_code(recovery, monkeypatch):
    service, user, redis, provider = recovery
    await service.request(user.id)
    await remove_cooldown(service, user, redis)
    codes = iter(["134679", "246810"])
    monkeypatch.setattr("app.auth.mobile_verification.generate_otp_code", lambda: next(codes))
    await service.request(user.id)
    assert provider.send_signup_otp.call_args.kwargs["code"] == "246810"


@pytest.mark.asyncio
async def test_hourly_send_cap_and_destination_limit(recovery):
    service, user, redis, provider = recovery
    for _ in range(5):
        await service.request(user.id)
        await remove_cooldown(service, user, redis)
    with pytest.raises(RateLimitError):
        await service.request(user.id)
    user.id = uuid4()  # Another account cannot evade a destination's cap.
    with pytest.raises(RateLimitError):
        await service.request(user.id)
    assert provider.send_signup_otp.await_count == 5


@pytest.mark.asyncio
async def test_stored_number_change_rejects_challenge(recovery):
    service, user, redis, provider = recovery
    await service.request(user.id)
    user.phone = "+919876543211"
    with pytest.raises(UnauthorizedError):
        await service.verify(user.id, "134679")
    assert user.phone_verified_at is None
    provider.verify_signup_otp.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_phone_and_already_verified_do_not_send(recovery):
    service, user, redis, provider = recovery
    user.phone = None
    assert (await service.request(user.id)).state == "phone_required"
    assert (await service.verify(user.id, "134679")).state == "phone_required"
    user.phone_verified_at = datetime.now(UTC)
    assert (await service.request(user.id)).phone_verified
    provider.send_signup_otp.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_role_email_and_provider_failure_fail_closed(recovery):
    service, user, redis, provider = recovery
    user.role = "admin"
    with pytest.raises(ForbiddenError):
        await service.request(user.id)
    user.role = "user"
    user.email_verified_at = None
    with pytest.raises(ForbiddenError):
        await service.request(user.id)
    user.email_verified_at = datetime.now(UTC)
    await service.request(user.id)
    provider.verify_signup_otp.side_effect = UnauthorizedError(
        "Invalid or expired verification code"
    )
    with pytest.raises(UnauthorizedError):
        await service.verify(user.id, "134679")
    assert user.phone_verified_at is None
    with pytest.raises(UnauthorizedError):
        await service.verify(user.id, "134679")
    assert provider.verify_signup_otp.await_count == 1


@pytest.mark.asyncio
async def test_scope_is_separate_from_signup(recovery):
    service, user, redis, _ = recovery
    signup = SignupOtpStore(redis, service.settings)
    await signup.store_otp(user.id, "phone", "112233")
    await service.request(user.id)
    with pytest.raises(UnauthorizedError):
        await service.verify(user.id, "112233")
    assert await signup.verify_and_consume(user.id, "phone", "112233")


@pytest.mark.asyncio
async def test_route_auth_and_strict_destination_contract():
    from app.api.dependencies.auth import CurrentUser, get_current_user
    from app.api.dependencies.rate_limit import auth_rate_limit, otp_verify_rate_limit
    from app.api.dependencies.services import get_auth_service
    from app.main import app
    from app.schemas.auth import MobileVerificationResponse

    uid = uuid4()
    fake = SimpleNamespace(
        mobile_verification=SimpleNamespace(
            request=AsyncMock(return_value=MobileVerificationResponse(state="code_sent")),
            verify=AsyncMock(
                return_value=MobileVerificationResponse(state="verified", phone_verified=True)
            ),
        )
    )
    app.dependency_overrides[auth_rate_limit] = lambda: None
    app.dependency_overrides[otp_verify_rate_limit] = lambda: None
    app.dependency_overrides[get_auth_service] = lambda: fake
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            for route in ("request", "verify"):
                r = await client.post(
                    "/api/v1/auth/mobile-verification/" + route,
                    json={"code": "134679"} if route == "verify" else {},
                )
                assert r.status_code == 401
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(
                uid, "synthetic@example.com", "user"
            )
            for route, body in (
                ("request", {"phone": "+919876543210"}),
                ("verify", {"code": "134679", "user_id": str(uuid4())}),
            ):
                assert (
                    await client.post("/api/v1/auth/mobile-verification/" + route, json=body)
                ).status_code == 422
            assert (
                await client.post("/api/v1/auth/mobile-verification/request", json={})
            ).status_code == 200
            assert (
                await client.post(
                    "/api/v1/auth/mobile-verification/verify", json={"code": "134679"}
                )
            ).status_code == 200
            fake.mobile_verification.request.assert_awaited_once_with(uid)
            fake.mobile_verification.verify.assert_awaited_once_with(uid, "134679")
    finally:
        app.dependency_overrides.clear()


def test_provider_url_redaction():
    from app.logging.request_redaction import redact_request_credentials

    value = redact_request_credentials(
        "https://control.msg91.com/api/v5/otp?authkey=secret&otp=134679&mobile=919876543210"
    )
    assert all(x not in value for x in ("secret", "134679", "919876543210"))


@pytest.mark.asyncio
async def test_msg91_custom_challenge_and_untrusted_error_privacy(caplog):
    import logging

    from app.exceptions import ServiceUnavailableError
    from app.integrations.phone_otp.msg91 import Msg91PhoneOtpProvider

    settings = Settings(
        phone_otp_backend="msg91",
        msg91_auth_key="synthetic-secret",
        msg91_template_id="synthetic-template",
    )
    response = httpx.Response(
        400,
        request=httpx.Request("POST", "https://example.invalid"),
        json={"type": "error", "message": "synthetic-secret 134679 +919876543210"},
    )
    client = SimpleNamespace(request=AsyncMock(return_value=response))
    provider = Msg91PhoneOtpProvider(settings, client=client)
    with caplog.at_level(logging.INFO), pytest.raises(ServiceUnavailableError):
        await provider.send_signup_otp(to_phone="+919876543210", code="134679")
    assert client.request.call_args.kwargs["params"]["otp"] == "134679"
    for record in caplog.records:
        assert not any(
            v in str(record.__dict__) for v in ("synthetic-secret", "134679", "+919876543210")
        )


@pytest.mark.asyncio
async def test_disabled_provider_never_sends(recovery):
    from app.exceptions import ServiceUnavailableError

    service, user, _, provider = recovery
    service.settings.phone_otp_enabled = False
    with pytest.raises(ServiceUnavailableError):
        await service.request(user.id)
    provider.send_signup_otp.assert_not_awaited()
    service.settings.phone_otp_enabled = True
    for backend in ("console", "staging_fixed"):
        service.settings.phone_otp_backend = backend
        with pytest.raises(ServiceUnavailableError):
            await service.request(user.id)
    provider.send_signup_otp.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_database_atomic_transition_and_concurrent_replay(monkeypatch):
    import asyncio
    import os

    from sqlalchemy import delete, select

    from app.db.session import async_session_factory
    from app.models.user import User
    from app.services.passport_engine_service import PassportEngineService

    settings = Settings(
        phone_otp_backend="msg91",
        msg91_auth_key="synthetic-secret",
        msg91_template_id="synthetic-template",
    )
    uid = uuid4()
    redis = Redis.from_url(os.environ["REDIS_URL"])
    provider = SimpleNamespace(send_signup_otp=AsyncMock(), verify_signup_otp=AsyncMock())
    scope = "existing_mobile_test_" + uid.hex

    def service(session):
        result = MobileVerificationService(session, settings, redis, None, provider)
        result.otp = SignupOtpStore(redis, settings, scope=scope)
        return result

    monkeypatch.setattr("app.auth.mobile_verification.generate_otp_code", lambda: "134679")
    try:
        async with async_session_factory() as session:
            session.add(
                User(
                    id=uid,
                    email=f"{uid}@example.invalid",
                    phone="+919876543219",
                    email_verified_at=datetime.now(UTC),
                    role="user",
                    is_active=True,
                )
            )
            await session.commit()
            assert (await service(session).request(uid)).state == "code_sent"

        async def verify():
            async with async_session_factory() as session:
                return await service(session).verify(uid, "134679")

        results = await asyncio.gather(verify(), verify())
        assert all(r.phone_verified for r in results)
        assert provider.verify_signup_otp.await_count == 1
        async with async_session_factory() as session:
            user = (await session.execute(select(User).where(User.id == uid))).scalar_one()
            assert user.phone_verified_at is not None
            engine = PassportEngineService.__new__(PassportEngineService)
            engine._session = session
            status = await engine.get_onboarding_status(uid)
            assert status.phone_verified and status.email_verified
            assert status.current_step == "complete_profile"
    finally:
        async with async_session_factory() as session:
            await session.execute(delete(User).where(User.id == uid))
            await session.commit()
        async for key in redis.scan_iter(match=f"*{scope}*"):
            await redis.delete(key)
        await redis.aclose()
