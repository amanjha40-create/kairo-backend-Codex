"""Synthetic State-B certification only; never use a live provider or account."""

import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from test_digilocker_eaadhaar import DOB, SECRET, signature, xml
from test_digilocker_lifecycle import harness  # noqa: F401

from app.config.settings import AppEnvironment as AppEnv
from app.db.session import async_session_factory
from app.exceptions import NotFoundError
from app.integrations.digilocker.eaadhaar import DigiLockerEAadhaar
from app.models import (
    DigiLockerConnection,
    DigiLockerIdentityVerification,
    TrustScoreSnapshot,
    User,
)
from app.ops.digilocker_aadhaar_entitlement_check import certify, parser, require_state_b
from app.services.digilocker_eaadhaar_service import DigiLockerEAadhaarService


def args(owner=None, connection=None):
    return SimpleNamespace(
        execute=True,
        consent_confirmed=True,
        consent_version="v1",
        approval_id=uuid4(),
        candidate_id=owner or uuid4(),
        connection_id=connection or uuid4(),
    )


def production_state_b(config):
    return config.model_copy(
        update={
            "app_env": AppEnv.PRODUCTION,
            "digilocker_eaadhaar_enabled": False,
            "digilocker_eaadhaar_entitlement_certified": False,
            "digilocker_token_encryption_active_key_id": "production-synthetic",
            "digilocker_token_encryption_keys": SecretStr(
                json.dumps(
                    {
                        "production-synthetic": base64.b64encode(bytes(range(32))).decode(),
                    }
                )
            ),
        }
    )


async def setup(h):
    connection = await h.activate()
    config = production_state_b(h.config)
    async with async_session_factory() as db:
        svc = DigiLockerEAadhaarService(db, config, h.redis)
        row = await db.get(DigiLockerConnection, connection.id)
        for purpose in ("access_token", "refresh_token"):
            setattr(
                row,
                "encrypted_" + purpose,
                svc._encrypt(row, purpose, SecretStr("synthetic-token")),
            )
        user = await db.get(User, h.ids[0])
        user.full_name, user.date_of_birth = "Test Candidate", DOB
        await db.commit()
    return config, args(h.ids[0], connection.id)


@pytest.mark.parametrize(
    "change",
    [
        {"digilocker_enabled": False},
        {"digilocker_eaadhaar_enabled": True},
        {"digilocker_eaadhaar_entitlement_certified": True},
        {"app_env": AppEnv.STAGING},
    ],
)
def test_operator_requires_production_state_b(change):
    from digilocker_helpers import settings

    config = production_state_b(settings()).model_copy(update=change)
    with pytest.raises(ValueError):
        require_state_b(config, args())


@pytest.mark.parametrize(
    "change",
    [
        {"execute": False},
        {"consent_confirmed": False},
        {"consent_version": "v0"},
        {"candidate_id": "private-email-canary@example.invalid"},
        {"approval_id": None},
    ],
)
def test_explicit_approval_account_and_consent_required(change):
    from digilocker_helpers import settings

    parameters = args()
    parameters.__dict__.update(change)
    with pytest.raises(ValueError):
        require_state_b(production_state_b(settings()), parameters)


def test_parser_does_not_echo_private_arguments(capsys):
    with pytest.raises(SystemExit):
        parser().parse_args(["--candidate-id", "private-email-canary@example.invalid"])
    output = capsys.readouterr()
    assert "private-email-canary" not in output.err + output.out


@pytest.mark.parametrize(
    "status,outcome",
    [
        (200, "ENTITLEMENT_CONFIRMED"),
        (403, "ENTITLEMENT_DENIED"),
        (401, "CONTROLLED_SESSION_RECONNECT_REQUIRED"),
        (404, "ACCOUNT_NOT_LINKED"),
        (500, "PROVIDER_TEMPORARY_FAILURE"),
        (503, "PROVIDER_TEMPORARY_FAILURE"),
    ],
)
async def test_single_fetch_integrity_persistence_and_safe_outcomes(harness, status, outcome):  # noqa: F811
    h = harness
    config, parameters = await setup(h)
    calls = []
    body = xml()

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/user"):
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=httpx.ByteStream(b'{"eaadhaar":"Y"}'),
            )
        assert request.url.path == "/public/oauth2/2/xml/eaadhaar"
        return httpx.Response(
            status,
            headers={"content-type": "application/xml", "hmac": signature(body, SECRET)},
            stream=httpx.ByteStream(body if status == 200 else b"private-error-canary"),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        async with async_session_factory() as db:
            svc = DigiLockerEAadhaarService(
                db, config, h.redis, aadhaar=DigiLockerEAadhaar(config, client=client)
            )
            snapshots = await db.scalar(select(func.count()).select_from(TrustScoreSnapshot))
            with pytest.raises(NotFoundError):
                await svc.availability(h.ids[0])
            result = await certify(svc, parameters)
            assert result["outcome"] == outcome
            assert result["derived_provenance_persisted"] is (status == 200)
            assert result["feature_flags_changed"] is False
            rows = list(
                (
                    await db.scalars(
                        select(DigiLockerIdentityVerification).where(
                            DigiLockerIdentityVerification.user_id == h.ids[0]
                        )
                    )
                ).all()
            )
            assert len(rows) == (1 if status == 200 else 0)
            if rows:
                assert rows[0].consent_version == "v1" and rows[0].integrity_result == "verified"
                stored = str({c.name: getattr(rows[0], c.name) for c in rows[0].__table__.columns})
                for value in (
                    "000000000000",
                    "synthetic-photo",
                    "Test Candidate",
                    "synthetic-token",
                ):
                    assert value not in stored
            assert (
                await db.scalar(select(func.count()).select_from(TrustScoreSnapshot)) == snapshots
            )
            assert "private-error-canary" not in json.dumps(result)
    assert calls == ["/public/oauth2/1/user", "/public/oauth2/2/xml/eaadhaar"]
    assert (
        not config.digilocker_eaadhaar_enabled
        and not config.digilocker_eaadhaar_entitlement_certified
    )


async def test_not_available_no_xml_and_connection_pin(harness):  # noqa: F811
    h = harness
    config, parameters = await setup(h)
    adapter = AsyncMock()
    adapter.availability.return_value = False
    async with async_session_factory() as db:
        svc = DigiLockerEAadhaarService(db, config, h.redis, aadhaar=adapter)
        wrong = args(h.ids[0], uuid4())
        assert (await certify(svc, wrong))["outcome"] == "CONTROLLED_ACCOUNT_REFUSED"
        adapter.availability.assert_not_called()
        assert (await certify(svc, parameters))["outcome"] == "ACCOUNT_NOT_LINKED"
        adapter.availability.assert_awaited_once()
        adapter.verify.assert_not_called()


async def test_bad_hmac_never_parses_or_persists(harness):  # noqa: F811
    config, parameters = await setup(harness)
    calls = []

    def handler(request):
        calls.append(request.url.path)
        content = b'{"eaadhaar":"Y"}' if len(calls) == 1 else xml()
        kind = "application/json" if len(calls) == 1 else "application/xml"
        return httpx.Response(200, headers={"content-type": kind}, stream=httpx.ByteStream(content))

    with patch("app.integrations.digilocker.eaadhaar.match_xml") as parse:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            async with async_session_factory() as db:
                svc = DigiLockerEAadhaarService(
                    db, config, harness.redis, aadhaar=DigiLockerEAadhaar(config, client=client)
                )
                assert (await certify(svc, parameters))["outcome"] == "SECURITY_FAILURE"
                parse.assert_not_called()
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(DigiLockerIdentityVerification)
                        .where(DigiLockerIdentityVerification.user_id == parameters.candidate_id)
                    )
                    == 0
                )
    assert len(calls) == 2


def test_no_operator_http_surface():
    from app.main import app

    assert all("entitlement_check" not in path for path in app.openapi()["paths"])
