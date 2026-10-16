import base64
import hmac
from datetime import date
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from digilocker_helpers import settings
from pydantic import SecretStr
from sqlalchemy import func, select
from test_digilocker_lifecycle import harness  # noqa: F401

from app.db.session import async_session_factory
from app.integrations.digilocker.eaadhaar import DigiLockerEAadhaar, match_xml, verify_integrity
from app.integrations.digilocker.provider import ProviderError
from app.models import DigiLockerIdentityVerification, TrustScoreSnapshot, User, UserDocument
from app.services.canonical_trust import resolve_identity
from app.services.digilocker_eaadhaar_service import DigiLockerEAadhaarService

TODAY = date(2026, 10, 16)
DOB = date(1990, 1, 2)
TOKEN = SecretStr("synthetic-bearer")
SECRET = SecretStr("synthetic-client-secret")


def test_historical_aadhaar_filename_minimization_does_not_mutate_row():
    from types import SimpleNamespace

    from app.user_documents.privacy import display_filename
    row = SimpleNamespace(document_type="aadhaar", original_filename="000000000000.pdf")
    assert display_filename(row) == "aadhaar-document"
    assert row.original_filename == "000000000000.pdf"
    row.document_type = "pan"
    assert display_filename(row) == row.original_filename


def xml(extra="", name="Test Candidate", dob="02-01-1990"):
    return (
        f"<AadhaarXmlSchema><KycRes><Rar>synthetic</Rar><UidData>"
        f"<Poi><dob>{dob}</dob><gender>X</gender><name>{name}</name></Poi>"
        "<Poa><co>synthetic</co><country>IN</country><dist>synthetic</dist>"
        "<lm>synthetic</lm><loc>synthetic</loc><pc>000000</pc>"
        "<state>synthetic</state><vtc>synthetic</vtc></Poa>"
        "<uid>000000000000</uid><tkn>synthetic-private-ref</tkn>"
        f"<Pht>synthetic-photo</Pht>{extra}</UidData></KycRes></AadhaarXmlSchema>"
    ).encode()


def signature(body, key=SECRET):
    return base64.b64encode(hmac.digest(key.get_secret_value().encode(), body, "sha256")).decode()


@pytest.mark.parametrize(
    "body,header,key",
    [
        (xml() + b" ", signature(xml()), SECRET),
        (xml().replace(b"Test", b"Fake"), signature(xml()), SECRET),
        (xml(), None, SECRET),
        (xml(), "!" * 44, SECRET),
        (xml(), signature(xml()), SecretStr("wrong-synthetic-key")),
    ],
    ids=["altered-space", "altered-content", "missing-header", "invalid-base64", "wrong-key"],
)
def test_integrity_failures(body, header, key):
    with pytest.raises(ProviderError) as error:
        verify_integrity(body, header, key)
    assert error.value.category == "integrity_failed"


def test_valid_integrity_and_minimized_match():
    body = xml("<Unknown>synthetic-extra</Unknown>")
    verify_integrity(body, signature(body), SECRET)
    result = match_xml(body, "Test Candidate", DOB, TODAY)
    assert result.result == "VERIFIED_MATCH"
    assert not any(
        value in str(result.diagnostics)
        for value in ["Test Candidate", "000000000000", "synthetic-photo", "synthetic-private-ref"]
    )


@pytest.mark.parametrize(
    "body",
    [
        b"broken",
        b"x" * (1024 * 1024 + 1),
        b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><AadhaarXmlSchema>&e;</AadhaarXmlSchema>',
        b'<!DOCTYPE x [<!ENTITY e "boom">]><AadhaarXmlSchema>&e;</AadhaarXmlSchema>',
        xml('<xi:include xmlns:xi="http://www.w3.org/2001/XInclude" href="https://invalid.test"/>'),
        xml("<x>" * 20 + "</x>" * 20),
        xml("<x/>" * 256),
        xml("<x>" + "z" * 8193 + "</x>"),
        xml("<Poi><name>Ambiguous</name><dob>02-01-1990</dob></Poi>"),
        xml(dob="1990"),
        xml(dob="02-01-2099"),
        xml().replace(b"<name>", b"<name><x>").replace(b"</name>", b"</x></name>"),
    ],
    ids=[
        "malformed",
        "oversized",
        "external-entity",
        "entity",
        "xinclude",
        "depth",
        "elements",
        "text",
        "duplicate-person",
        "year-only",
        "future-dob",
        "nested-name",
    ],
)
def test_bounded_xml_rejects_unsafe_or_ambiguous(body):
    with pytest.raises(ProviderError) as error:
        match_xml(body, "Test Candidate", DOB, TODAY)
    assert error.value.category == "invalid_response"


@pytest.mark.parametrize(
    "code,category",
    [
        (401, "invalid_token"),
        (404, "aadhaar_not_linked"),
        (403, "insufficient_scope"),
        (500, "provider_unavailable"),
        (503, "provider_unavailable"),
        (302, "provider_unavailable"),
    ],
)
async def test_safe_failure_no_retry_or_raw_body(code, category, caplog):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(code, stream=httpx.ByteStream(b"private-provider-canary"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError) as error:
            await DigiLockerEAadhaar(settings(), client=client).verify(
                TOKEN, name="Test Candidate", dob=DOB, today=TODAY
            )
    assert error.value.category == category
    assert len(calls) == 1
    assert "private-provider-canary" not in str(error.value) + caplog.text


async def test_endpoint_raw_integrity_before_parse():
    body = xml()
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET" and not request.url.query
        assert request.url.path == "/public/oauth2/2/xml/eaadhaar"
        assert request.headers["accept"] == "application/xml"
        return httpx.Response(
            200,
            headers={"content-type": "application/xml", "hmac": signature(body)},
            stream=httpx.ByteStream(body),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await DigiLockerEAadhaar(settings(), client=client).verify(
            TOKEN, name="Test Candidate", dob=DOB, today=TODAY
        )
    assert result.result == "VERIFIED_MATCH" and len(calls) == 1
    with patch("app.integrations.digilocker.eaadhaar.match_xml") as parser:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200, headers={"content-type": "application/xml"}, stream=httpx.ByteStream(body)
                )
            )
        ) as client:
            with pytest.raises(ProviderError) as error:
                await DigiLockerEAadhaar(settings(), client=client).verify(
                    TOKEN, name="Test Candidate", dob=DOB, today=TODAY
                )
            assert error.value.category == "integrity_failed"
        parser.assert_not_called()


@pytest.mark.parametrize("flag,expected", [("Y", True), ("N", False), ("other", None)])
async def test_user_details_only_returns_availability(flag, expected):
    import json

    body = json.dumps(
        {"eaadhaar": flag, "name": "private-canary", "picture": "private-photo"}
    ).encode()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, headers={"content-type": "application/json"}, stream=httpx.ByteStream(body)
            )
        )
    ) as client:
        adapter = DigiLockerEAadhaar(settings(), client=client)
        if expected is None:
            with pytest.raises(ProviderError):
                await adapter.availability(TOKEN)
        else:
            assert await adapter.availability(TOKEN) is expected


def test_flags_and_endpoint_fail_closed():
    from app.integrations.digilocker.configuration import DigiLockerConfigurationError

    assert not settings().digilocker_eaadhaar_enabled
    with pytest.raises(ValueError):
        settings(digilocker_enabled=False, digilocker_eaadhaar_enabled=True)
    with pytest.raises(DigiLockerConfigurationError):
        settings(
            digilocker_eaadhaar_url="https://digilocker.meripehchaan.gov.in/public/oauth2/3/xml/eaadhaar"
        )
    with pytest.raises(DigiLockerConfigurationError):
        settings(digilocker_user_details_url="https://attacker.invalid/user")


async def test_persistence_only_derived_and_repeat_no_score_snapshot(harness):  # noqa: F811
    from app.models.permanent_address import PermanentAddressSession, PermanentAddressVersion

    h = harness
    await h.activate()
    config = h.config.model_copy(update={"digilocker_eaadhaar_enabled": True})
    adapter = AsyncMock()
    adapter.availability.return_value = True
    adapter.verify.return_value = match_xml(xml(), "Test Candidate", DOB, TODAY)
    async with async_session_factory() as session:
        user = await session.get(User, h.ids[0])
        user.full_name, user.date_of_birth = "Test Candidate", DOB
        await session.commit()
        address = PermanentAddressVersion(
            user_id=user.id,
            version=1,
            claimed_address={"synthetic": True},
            address_hash="0" * 64,
            document_status="REQUIRED",
        )
        session.add(address)
        await session.commit()
        address_before = {c.name: getattr(address, c.name) for c in address.__table__.columns}
        before = await session.scalar(select(func.count()).select_from(TrustScoreSnapshot))
        service = DigiLockerEAadhaarService(session, config, h.redis, aadhaar=adapter)
        one = await service.verify_aadhaar(user.id, consent=True, consent_version="v1")
        two = await service.verify_aadhaar(user.id, consent=True, consent_version="v1")
        assert one["id"] == two["id"] and one["source_type"] == "eaadhaar"
        row = await session.scalar(
            select(DigiLockerIdentityVerification).where(
                DigiLockerIdentityVerification.user_id == user.id
            )
        )
        stored = str({c.name: getattr(row, c.name) for c in row.__table__.columns})
        assert not any(
            v in stored
            for v in [
                "000000000000",
                "synthetic-photo",
                "Test Candidate",
                "<",
                "synthetic-private-ref",
            ]
        )
        assert row.issuer_id is None and row.issuer_name is None
        assert (await resolve_identity(session, user))["state"] == "verified"
        assert await session.scalar(select(func.count()).select_from(TrustScoreSnapshot)) == before
        assert (
            await session.scalar(
                select(func.count())
                .select_from(UserDocument)
                .where(UserDocument.user_id == user.id)
            )
            == 0
        )
        await session.refresh(address)
        assert {
            c.name: getattr(address, c.name) for c in address.__table__.columns
        } == address_before
        assert (
            await session.scalar(
                select(func.count())
                .select_from(PermanentAddressSession)
                .where(PermanentAddressSession.address_version_id == address.id)
            )
            == 0
        )
        assert await service.history(h.ids[1]) == {"items": [], "identity_verified": False}


async def test_aadhaar_does_not_stack_identity_points():
    from datetime import UTC, datetime

    from test_digilocker_trust import source
    from test_trust_score_v1 import _Session, _settings, _user

    from app.services.trust_score_service import TrustScoreService

    now = datetime.now(UTC)
    user = _user(updated_at=now, trust_score_consent_at=now)
    session = _Session(user)
    session.digilocker = [source(user, "PANCR"), source(user, "DRVLC")]
    service = TrustScoreService(session, _settings())
    before = await service.calculate_trust_score(user.id)
    session.digilocker.append(source(user, "EAADHAAR"))
    after = await service.calculate_trust_score(user.id)
    assert after.overall == before.overall and after.breakdown.identity == 100
    assert len([c for c in after.positive_contributors if c.code == "identity_authoritative"]) == 1


@pytest.mark.parametrize(
    "category",
    [
        "invalid_token",
        "insufficient_scope",
        "aadhaar_not_linked",
        "integrity_failed",
        "transport_error",
    ],
)
async def test_provider_failure_never_persists_verification(harness, category):  # noqa: F811
    from app.exceptions import AppException

    await harness.activate()
    adapter = AsyncMock()
    adapter.availability.return_value = True
    adapter.verify.side_effect = ProviderError(category)
    async with async_session_factory() as session:
        service = DigiLockerEAadhaarService(
            session,
            harness.config.model_copy(update={"digilocker_eaadhaar_enabled": True}),
            harness.redis,
            aadhaar=adapter,
        )
        with pytest.raises(AppException):
            await service.verify_aadhaar(harness.ids[0], consent=True, consent_version="v1")
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DigiLockerIdentityVerification)
                .where(DigiLockerIdentityVerification.user_id == harness.ids[0])
            )
            == 0
        )
    adapter.verify.assert_awaited_once()
    if category == "invalid_token":
        assert (await harness.connection()).status == "reconnect_required"


async def test_other_owner_cannot_use_connected_users_token(harness):  # noqa: F811
    from app.exceptions import AppException

    await harness.activate()
    adapter = AsyncMock()
    async with async_session_factory() as session:
        service = DigiLockerEAadhaarService(
            session,
            harness.config.model_copy(update={"digilocker_eaadhaar_enabled": True}),
            harness.redis,
            aadhaar=adapter,
        )
        with pytest.raises(AppException):
            await service.verify_aadhaar(harness.ids[1], consent=True, consent_version="v1")
    adapter.availability.assert_not_called()
    adapter.verify.assert_not_called()


async def test_consent_and_disabled_prevent_provider_calls(harness):  # noqa: F811
    adapter = AsyncMock()
    async with async_session_factory() as session:
        for enabled, consent in [(False, True), (True, False)]:
            service = DigiLockerEAadhaarService(
                session,
                harness.config.model_copy(update={"digilocker_eaadhaar_enabled": enabled}),
                harness.redis,
                aadhaar=adapter,
            )
            from app.exceptions import AppException

            with pytest.raises(AppException):
                await service.verify_aadhaar(harness.ids[0], consent=consent, consent_version="v1")
    adapter.verify.assert_not_called()
    adapter.availability.assert_not_called()


async def test_generic_aadhaar_orm_privacy(harness):  # noqa: F811
    from app.schemas.user_document import UserDocumentResponse

    async with async_session_factory() as session:
        doc = UserDocument(
            user_id=harness.ids[0],
            document_type="aadhaar",
            document_number="000000000000",
            original_filename="000000000000.pdf",
            object_key="synthetic/" + str(harness.ids[0]),
            content_type="application/pdf",
            byte_size=1,
            checksum_sha256="0" * 64,
            extracted_payload={"number": "000000000000"},
            reviewer_note="000000000000",
        )
        session.add(doc)
        await session.commit()
        await session.refresh(doc)
        assert (
            doc.document_number is None
            and doc.extracted_payload is None
            and doc.reviewer_note is None
        )
        doc.document_number = "000000000000"
        await session.commit()
        await session.refresh(doc)
        assert doc.document_number is None
        assert "000000000000" not in UserDocumentResponse.model_validate(doc).model_dump_json()


@pytest.mark.parametrize("error", [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError])
async def test_transport_failure_is_safe_and_not_retried(error):
    calls = []

    def handler(request):
        calls.append(request)
        raise error("private-transport-canary", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError) as caught:
            await DigiLockerEAadhaar(settings(), client=client).availability(TOKEN)
    assert caught.value.category == "transport_error"
    assert "canary" not in str(caught.value) and len(calls) == 1


@pytest.mark.parametrize(
    "body,headers,category",
    [
        (b"x" * (1024 * 1024 + 1), {"content-type": "application/xml"}, "response_too_large"),
        (
            b"broken",
            {"content-type": "application/xml", "hmac": signature(b"broken")},
            "invalid_response",
        ),
        (xml(), {"content-type": "application/json"}, "invalid_response"),
        (
            xml(),
            {"content-type": "application/xml", "content-encoding": "gzip"},
            "invalid_response",
        ),
    ],
    ids=["oversized", "malformed-signed-xml", "wrong-mime", "compressed"],
)
async def test_transport_body_limits(body, headers, category):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, headers=headers, stream=httpx.ByteStream(body))
        )
    ) as client:
        with pytest.raises(ProviderError) as caught:
            await DigiLockerEAadhaar(settings(), client=client).verify(
                TOKEN, name="Test Candidate", dob=DOB, today=TODAY
            )
    assert caught.value.category == category


async def test_production_entitlement_gate_cannot_be_bypassed(harness):  # noqa: F811
    from app.config.settings import AppEnvironment
    from app.exceptions import NotFoundError

    adapter = AsyncMock()
    config = harness.config.model_copy(
        update={
            "app_env": AppEnvironment.PRODUCTION,
            "digilocker_eaadhaar_enabled": True,
            "digilocker_eaadhaar_entitlement_certified": False,
        }
    )
    async with async_session_factory() as session:
        service = DigiLockerEAadhaarService(session, config, harness.redis, aadhaar=adapter)
        with pytest.raises(NotFoundError):
            await service.verify_aadhaar(harness.ids[0], consent=True, consent_version="v1")
    adapter.verify.assert_not_called()
    adapter.availability.assert_not_called()


async def test_routes_require_auth_strict_consent_owner_and_minimize_response():
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.api.v1.routes.digilocker import get_eaadhaar_service
    from app.auth.deps import CurrentUser, get_current_user
    from app.config import get_settings
    from app.main import app

    principal = CurrentUser(id=uuid4(), email="synthetic@example.invalid", role="user")
    service = AsyncMock()
    service.availability.return_value = {
        "available": True,
        "entitlement_confirmed": False,
        "photo": "private-canary",
    }
    service.verify_aadhaar.return_value = {
        "id": str(uuid4()),
        "source": "digilocker",
        "source_type": "eaadhaar",
        "document_type": "EAADHAAR",
        "integrity_result": "verified",
        "match_result": "VERIFIED_MATCH",
        "match_reason": None,
        "verified_at": datetime.now(UTC),
        "document_valid_until": None,
        "consent_purpose": "identity_verification",
        "consent_version": "v1",
        "consented_at": datetime.now(UTC),
        "current": True,
        "raw": "private-canary",
    }
    old = app.dependency_overrides.copy()
    app.dependency_overrides[get_eaadhaar_service] = lambda: service
    app.dependency_overrides[get_settings] = lambda: settings()
    root = "/api/v1/integrations/digilocker/eaadhaar"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            for path, method in [("/availability", "GET"), ("/verify", "POST")]:
                assert (await client.request(method, root + path)).status_code == 401
            app.dependency_overrides[get_current_user] = lambda: principal
            response = await client.get(root + "/availability")
            assert response.json() == {"available": True, "entitlement_confirmed": False}
            for body in [
                {"consent": "true", "consent_version": "v1"},
                {"consent": True, "consent_version": "v2"},
                {"consent": True, "consent_version": "v1", "user_id": str(uuid4())},
            ]:
                assert (await client.post(root + "/verify", json=body)).status_code == 422
            service.verify_aadhaar.assert_not_awaited()
            response = await client.post(
                root + "/verify", json={"consent": True, "consent_version": "v1"}
            )
            assert response.status_code == 200 and "canary" not in response.text
            assert response.headers["cache-control"] == "no-store"
            service.verify_aadhaar.assert_awaited_once_with(
                principal.id, consent=True, consent_version="v1"
            )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old)
