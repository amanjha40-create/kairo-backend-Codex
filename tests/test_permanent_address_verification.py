import base64
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import engine
from app.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    ValidationAppError,
)
from app.models.permanent_address import PermanentAddressSession, PermanentAddressVersion
from app.models.user import User
from app.models.user_document import UserDocument
from app.schemas.permanent_address import (
    AddressEvidenceInput,
    AddressReviewInput,
    LocationCancelInput,
    LocationCompleteInput,
    LocationSample,
    PermanentAddressInput,
)
from app.services.document_pack_storage import ObjectBinding
from app.services.permanent_address_geocoder import TargetCipher
from app.services.permanent_address_policy import (
    LocationPolicy,
    calendar_day,
    count_days,
    evaluate_location,
    overall_status,
)
from app.services.permanent_address_service import PermanentAddressService

NOW = datetime(2026, 10, 10, 5, tzinfo=UTC)
ADDRESS = PermanentAddressInput(
    address_line_1="123 Synthetic Road", city="Jaipur", state="Rajasthan", postal_code="302020"
)


def samples(start, **changes):
    return [
        LocationSample(
            latitude=0.0,
            longitude=0.0,
            accuracy_m=10.0,
            timestamp=start + timedelta(seconds=i * 8),
            **changes,
        )
        for i in range(5)
    ]


@pytest.mark.parametrize("kind", ["precise_address", "approximate_address"])
def test_multiple_samples_match(kind):
    assert (
        evaluate_location(samples(NOW), (0, 0), NOW, NOW + timedelta(seconds=33), kind).result
        == "MATCHED"
    )


def test_outside_not_closest_sample():
    values = samples(NOW)
    for sample in values:
        sample.latitude = 0.01
    assert (
        evaluate_location(
            values, (0, 0), NOW, NOW + timedelta(seconds=33), "precise_address"
        ).result
        == "OUTSIDE_EXPECTED_AREA"
    )
    values[0].latitude = 0.0
    assert (
        evaluate_location(
            values, (0, 0), NOW, NOW + timedelta(seconds=33), "precise_address"
        ).result
        == "RETRY_REQUIRED"
    )


def test_poor_accuracy_and_mock():
    values = samples(NOW)
    values[0].accuracy_m = 500
    assert (
        evaluate_location(
            values, (0, 0), NOW, NOW + timedelta(seconds=33), "precise_address"
        ).result
        == "RETRY_REQUIRED"
    )
    assert (
        evaluate_location(
            samples(NOW, mock_location=True),
            (0, 0),
            NOW,
            NOW + timedelta(seconds=33),
            "precise_address",
        ).result
        == "NEEDS_REVIEW"
    )


@pytest.mark.parametrize("delta", [0, 10, 121])
def test_server_duration_is_authoritative(delta):
    assert (
        evaluate_location(
            samples(NOW), (0, 0), NOW, NOW + timedelta(seconds=delta), "precise_address"
        ).result
        == "RETRY_REQUIRED"
    )


def test_fake_sample_clock_rejected():
    assert (
        evaluate_location(
            samples(NOW + timedelta(days=1)),
            (0, 0),
            NOW,
            NOW + timedelta(seconds=33),
            "precise_address",
        ).result
        == "RETRY_REQUIRED"
    )


def test_day_count_distinct_and_window():
    today = calendar_day(NOW)
    assert count_days([today] * 3, NOW, NOW) == 1
    assert (
        count_days(
            [today, today + timedelta(days=1), today + timedelta(days=2)],
            NOW,
            NOW + timedelta(days=2),
        )
        == 3
    )
    assert count_days([today] * 3, NOW, NOW + timedelta(days=7)) == 0


@pytest.mark.parametrize(
    "document,checks,status",
    [
        ("REQUIRED", 3, "LOCATION_CONFIRMED"),
        ("MATCH", 0, "LOCATION_CHECK_REQUIRED"),
        ("MATCH", 2, "LOCATION_CHECK_REQUIRED"),
        ("MATCH", 3, "PERMANENT_ADDRESS_VERIFIED"),
    ],
)
def test_document_and_gps_conjunction(document, checks, status):
    assert overall_status(document, checks, "READY") == status


@pytest.mark.parametrize(
    "field,value",
    [("latitude", 91), ("longitude", 181), ("accuracy_m", 0), ("latitude", float("nan"))],
)
def test_malformed_sample_rejected(field, value):
    data = samples(NOW)[0].model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        LocationSample(**data)


def test_client_verified_flag_rejected():
    with pytest.raises(ValidationError):
        PermanentAddressInput(**ADDRESS.model_dump(), verified=True)


def test_radius_cannot_expand_unbounded():
    with pytest.raises(ValueError):
        LocationPolicy(approximate_radius_m=151)


def settings():
    return get_settings().model_copy(
        update={
            "permanent_address_enabled": True,
            "permanent_address_key_id": "test-address-v1",
            "permanent_address_keys": SecretStr(
                json.dumps({"test-address-v1": base64.b64encode(b"x" * 32).decode()})
            ),
        }
    )


def test_cipher_context_and_plaintext():
    cipher = TargetCipher(settings())
    owner, version = uuid4(), uuid4()
    clear = {"position": [0.0, 0.0], "normalized_address": {"Street": "Synthetic Road"}}
    encrypted = cipher.encrypt(clear, owner, version)
    assert b"position" not in encrypted and b"Synthetic" not in encrypted
    assert cipher.decrypt(encrypted, cipher.active, owner, version) == clear
    with pytest.raises(ServiceUnavailableError):
        cipher.decrypt(encrypted, cipher.active, uuid4(), version)
    with pytest.raises(ServiceUnavailableError):
        cipher.decrypt(encrypted, cipher.active, owner, uuid4())


class FakeGeocoder:
    def __init__(self):
        self.calls = 0

    async def geocode(self, address):
        self.calls += 1
        return {"quality": "precise_address", "provider": "amazon_location"}, {
            "position": [0.0, 0.0],
            "normalized_address": {},
        }


class FakeStorage:
    etag = "synthetic-etag"

    async def inspect(self, key):
        return ObjectBinding(key, None, self.etag, 1, "application/pdf")


@pytest.fixture
async def case():
    async with engine.connect() as conn:
        outer = await conn.begin()
        async with AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as db:
            users = [
                User(email=f"{uuid4()}@example.test", role="user", is_active=True) for _ in range(3)
            ]
            db.add_all(users)
            await db.flush()
            clock = [NOW]
            geocoder = FakeGeocoder()
            svc = PermanentAddressService(
                db, settings(), geocoder=geocoder, clock=lambda: clock[0], storage=FakeStorage()
            )
            yield db, users, svc, clock, geocoder
        await outer.rollback()


async def prepare(case):
    db, users, svc, clock, geocoder = case
    state = await svc.save_address(users[0].id, ADDRESS)
    return state.address_version_id


async def check(case, version):
    db, users, svc, clock, geocoder = case
    start = clock[0]
    challenge = await svc.start(users[0].id, version)
    clock[0] += timedelta(seconds=33)
    payload = LocationCompleteInput(challenge=challenge.challenge, samples=samples(start))
    return await svc.finish(users[0].id, challenge.session_id, payload), challenge, payload


async def evidence(case, version):
    db, users, svc, _, _ = case
    document = UserDocument(
        user_id=users[0].id,
        document_type="address_proof",
        object_key=f"qa/{uuid4()}",
        original_filename="synthetic.pdf",
        content_type="application/pdf",
        byte_size=1,
        checksum_sha256="a" * 64,
        verification_status="approved",
    )
    db.add(document)
    await db.flush()
    await svc.attach_evidence(
        users[0].id, AddressEvidenceInput(address_version_id=version, document_id=document.id)
    )
    return document


@pytest.mark.asyncio
async def test_address_dedup_and_version_reset(case):
    db, users, svc, clock, geo = case
    version = await prepare(case)
    await svc.save_address(users[0].id, ADDRESS)
    assert geo.calls == 1
    await check(case, version)
    changed = ADDRESS.model_copy(update={"address_line_1": "124 Synthetic Road"})
    state = await svc.save_address(users[0].id, changed)
    assert state.address_version == 2 and state.successful_gps_checks == 0 and geo.calls == 2
    assert (await db.get(PermanentAddressVersion, version)).invalidated_at is not None
    assert len(list((await db.scalars(select(PermanentAddressSession))).all())) >= 1


@pytest.mark.asyncio
async def test_three_days_alone_not_verified_then_document_match(case):
    db, users, svc, clock, _ = case
    version = await prepare(case)
    for offset in range(3):
        clock[0] = NOW + timedelta(days=offset)
        state, _, _ = await check(case, version)
    assert state.successful_gps_checks == 3 and state.status == "LOCATION_CONFIRMED"
    document = await evidence(case, version)
    assert (await svc.state(users[0].id)).status != "PERMANENT_ADDRESS_VERIFIED"
    await svc.review(
        users[2].id,
        version,
        AddressReviewInput(document_id=document.id, outcome="MATCH", observed_address=ADDRESS),
    )
    assert (await svc.state(users[0].id)).status == "PERMANENT_ADDRESS_VERIFIED"


@pytest.mark.asyncio
async def test_same_day_replay_and_cross_user(case):
    _, users, svc, clock, _ = case
    version = await prepare(case)
    state, challenge, payload = await check(case, version)
    assert state.successful_gps_checks == 1
    with pytest.raises(ConflictError):
        await svc.start(users[0].id, version)
    with pytest.raises(ConflictError):
        await svc.finish(users[0].id, challenge.session_id, payload)
    with pytest.raises(NotFoundError):
        await svc.finish(users[1].id, challenge.session_id, payload)
    with pytest.raises(NotFoundError):
        await svc.start(users[1].id, version)


@pytest.mark.asyncio
async def test_cross_user_evidence_and_self_review(case):
    _, users, svc, _, _ = case
    version = await prepare(case)
    document = await evidence(case, version)
    foreign = await svc.save_address(users[1].id, ADDRESS)
    with pytest.raises(NotFoundError):
        await svc.attach_evidence(
            users[1].id,
            AddressEvidenceInput(
                address_version_id=foreign.address_version_id, document_id=document.id
            ),
        )
    with pytest.raises(ForbiddenError):
        await svc.review(
            users[0].id,
            version,
            AddressReviewInput(document_id=document.id, outcome="MATCH", observed_address=ADDRESS),
        )


@pytest.mark.asyncio
async def test_superseded_evidence_invalidates_match(case):
    db, users, svc, clock, _ = case
    version = await prepare(case)
    document = await evidence(case, version)
    await svc.review(
        users[2].id,
        version,
        AddressReviewInput(document_id=document.id, outcome="MATCH", observed_address=ADDRESS),
    )
    document.superseded_at = NOW
    await db.flush()
    assert (await svc.state(users[0].id)).document_status == "NEEDS_REVIEW"


@pytest.mark.asyncio
async def test_expired_window_starts_new_cycle_preserving_history(case):
    db, users, svc, clock, _ = case
    version = await prepare(case)
    await check(case, version)
    clock[0] = NOW + timedelta(days=8)
    state, _, _ = await check(case, version)
    assert state.successful_gps_checks == 1
    assert (await db.get(PermanentAddressVersion, version)).cycle == 2


@pytest.mark.asyncio
async def test_public_dto_has_no_coordinates_or_provider_internals(case):
    _, users, svc, _, _ = case
    await prepare(case)
    output = (await svc.state(users[0].id)).model_dump_json()
    for value in (
        "target_encrypted",
        "position",
        "latitude",
        "longitude",
        "MatchScores",
        "challenge_hash",
    ):
        assert value not in output


@pytest.mark.asyncio
async def test_completed_pending_upload_is_reviewable_without_identity_approval(case):
    db, users, svc, _, _ = case
    version = await prepare(case)
    doc = await evidence(case, version)
    doc.verification_status = "pending"
    await db.flush()
    assert (await svc.available_evidence(users[0].id))["items"][0]["id"] == doc.id
    await svc.review(
        users[2].id,
        version,
        AddressReviewInput(document_id=doc.id, outcome="MATCH", observed_address=ADDRESS),
    )
    assert (await svc.state(users[0].id)).document_status == "MATCH"
    assert doc.verification_status == "pending"  # No global identity/Trust Score change.
    assert (await svc.state(users[0].id)).status != "PERMANENT_ADDRESS_VERIFIED"


@pytest.mark.asyncio
async def test_storage_replacement_invalidates_address_document_match(case):
    _, users, svc, _, _ = case
    version = await prepare(case)
    doc = await evidence(case, version)
    await svc.review(
        users[2].id,
        version,
        AddressReviewInput(document_id=doc.id, outcome="MATCH", observed_address=ADDRESS),
    )
    svc.storage.etag = "changed-object"
    assert (await svc.state(users[0].id)).document_status == "NEEDS_REVIEW"
    with pytest.raises(ConflictError):
        await svc.review(
            users[2].id,
            version,
            AddressReviewInput(document_id=doc.id, outcome="MATCH", observed_address=ADDRESS),
        )


@pytest.mark.asyncio
async def test_no_raw_samples_persisted_and_cancel_is_single_use(case):
    db, users, svc, _, _ = case
    version = await prepare(case)
    challenge = await svc.start(users[0].id, version)
    payload = LocationCancelInput(challenge=challenge.challenge)
    state = await svc.finish(users[0].id, challenge.session_id, payload, cancel=True)
    assert state.successful_gps_checks == 0 and state.last_location_result == "CANCELLED"
    with pytest.raises(ConflictError):
        await svc.finish(users[0].id, challenge.session_id, payload, cancel=True)
    state, challenge, _ = await check(case, version)
    record = await db.get(PermanentAddressSession, challenge.session_id)
    assert record.derived_evidence["result"] == "MATCHED"
    assert not {"latitude", "longitude", "samples", "position"}.intersection(
        record.derived_evidence
    )


@pytest.mark.asyncio
async def test_expired_challenge_never_counts(case):
    _, users, svc, clock, _ = case
    version = await prepare(case)
    challenge = await svc.start(users[0].id, version)
    clock[0] += timedelta(seconds=121)
    state = await svc.finish(
        users[0].id,
        challenge.session_id,
        LocationCompleteInput(challenge=challenge.challenge, samples=samples(NOW)),
    )
    assert state.successful_gps_checks == 0 and state.last_location_result == "RETRY_REQUIRED"


@pytest.mark.asyncio
async def test_monthly_paid_call_limit_and_failure_dedup(case):
    _, users, svc, _, geo = case
    svc.settings = svc.settings.model_copy(update={"permanent_address_monthly_geocode_limit": 1})
    await prepare(case)
    with pytest.raises(RateLimitError):
        await svc.save_address(
            users[0].id, ADDRESS.model_copy(update={"address_line_1": "Another Road"})
        )
    assert geo.calls == 1


@pytest.mark.asyncio
async def test_review_requires_structure_and_preserves_conflict(case):
    _, users, svc, _, _ = case
    version = await prepare(case)
    doc = await evidence(case, version)
    with pytest.raises(ValidationAppError):
        await svc.review(
            users[2].id, version, AddressReviewInput(document_id=doc.id, outcome="MATCH")
        )
    wrong = ADDRESS.model_copy(update={"postal_code": "400051"})
    await svc.review(
        users[2].id,
        version,
        AddressReviewInput(document_id=doc.id, outcome="MATCH", observed_address=wrong),
    )
    assert (await svc.state(users[0].id)).document_status == "MISMATCH"
    listing = await svc.review_queue(users[2].id)
    assert "claimed_address" not in json.dumps(listing, default=str)


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_test_clock_cannot_be_injected_into_live_service(environment):
    with pytest.raises(ValueError):
        PermanentAddressService(
            None, settings().model_copy(update={"app_env": environment}), clock=lambda: NOW
        )


def test_production_cannot_enable_v1():
    svc = PermanentAddressService(None, settings().model_copy(update={"app_env": "production"}))
    assert not svc.enabled()


@pytest.mark.asyncio
async def test_address_api_auth_review_permissions_and_error_privacy(case):
    from httpx import ASGITransport, AsyncClient

    from app.api.v1.routes.permanent_address import service
    from app.auth.deps import CurrentUser, get_current_user
    from app.main import app

    _, users, svc, _, _ = case
    transport = ASGITransport(app=app)
    try:
        app.dependency_overrides[service] = lambda: svc
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/api/v1/permanent-address")).status_code == 401
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(
                id=users[0].id, email="qa@example.test", role="user"
            )
            assert (await client.get("/api/v1/permanent-address/reviews")).status_code == 403
            response = await client.post(
                f"/api/v1/permanent-address/sessions/{uuid4()}/complete",
                json={
                    "challenge": "private-synthetic-challenge-value-" * 2,
                    "samples": [{"latitude": "private-synthetic-coordinate"}],
                },
            )
            assert response.status_code == 422
            assert "private-synthetic" not in response.text
    finally:
        app.dependency_overrides.clear()
