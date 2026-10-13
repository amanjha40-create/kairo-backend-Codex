import asyncio
import json
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import engine
from app.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationAppError,
)
from app.models.permanent_address import PermanentAddressGeocodeBudget as Budget
from app.models.permanent_address import PermanentAddressSession as Session
from app.models.trust_score_snapshot import TrustScoreSnapshot
from app.models.user import User
from app.models.user_account_event import UserAccountEvent
from app.schemas.permanent_address import (
    AddressReviewInput,
    LocationCompleteInput,
    LocationReviewResolutionInput,
    ManualLocationReviewInput,
)
from app.services.permanent_address_geocoder import TargetCipher
from app.services.permanent_address_manual_review import PendingTargetCipher, manual_eligible
from app.services.permanent_address_onsite import precise_area_decision
from app.services.permanent_address_service import PermanentAddressService
from tests.test_permanent_address_onsite import eligible, result
from tests.test_permanent_address_verification import (
    ADDRESS,
    NOW,
    FakeGeocoder,
    FakeStorage,
    check,
    evidence,
    samples,
    settings,
)
from tests.test_permanent_address_verification import case as case


def conflict_decision():
    item = result()
    item["Address"].update(Street="Other Synthetic Street", AddressNumber="999")
    return precise_area_decision(ADDRESS.model_dump(), [item])


async def pending(case, *, document=False):
    db, users, svc, _, geo = case
    row = await eligible(case)
    geo.confirm_area.return_value = conflict_decision()
    _, challenge, _ = await check(case, row.id)
    users[2].role, users[2].email_verified_at = "admin", NOW
    await db.flush()
    attempt = await db.get(Session, challenge.session_id)
    if document:
        doc = await evidence(case, row.id)
        await svc.review(
            users[2].id,
            row.id,
            AddressReviewInput(
                document_id=doc.id,
                outcome="MATCH",
                observed_address=ADDRESS,
            ),
        )
    return row, attempt


def payload(users, outcome="APPROVE_ONSITE_LOCATION"):
    return ManualLocationReviewInput(
        candidate_id=users[0].id, idempotency_key=uuid4(), outcome=outcome
    )


async def events(db, owner):
    return list(
        (
            await db.scalars(
                select(UserAccountEvent).where(
                    UserAccountEvent.user_id == owner,
                    UserAccountEvent.event_type == "permanent_address_location_review",
                )
            )
        ).all()
    )


async def test_pending_is_encrypted_separate_and_private(case, caplog):
    db, users, svc, _, _ = case
    row, attempt = await pending(case)
    assert attempt.pending_target_encrypted and attempt.pending_target_key_id
    assert b"position" not in attempt.pending_target_encrypted
    assert attempt.manual_review_status == "pending"
    assert row.target_source == "provider_geocode" and not row.target_confirmed_at
    assert not row.geocode_metadata.get("provider_target_superseded")
    state = await svc.state(users[0].id)
    assert (
        state.successful_gps_checks == 0
        and state.manual_review_status == "waiting_for_address_document"
    )
    assert not state.can_start_location
    view = await svc.manual_location_detail(users[2].id, row.id, attempt.id)
    assert not view["approval_eligible"] and view["pending_target_available"]
    assert view["gps_quality"] == "PASS" and view["accepted_sample_count"] == 5
    assert len((await svc.manual_location_queue(users[2].id))["items"]) == 1
    for output in (
        state.model_dump_json(),
        json.dumps(view, default=str),
        caplog.text,
        json.dumps(attempt.derived_evidence),
        json.dumps(await events(db, users[0].id)),
    ):
        for forbidden in (
            "pending_target_encrypted",
            "pending_target_key_id",
            "position",
            "latitude",
            "longitude",
        ):
            assert forbidden not in output


@pytest.mark.parametrize("changed", ["owner", "version", "attempt", "active", "tamper"])
async def test_pending_encryption_context(case, changed):
    _, users, _, _, _ = case
    row, attempt = await pending(case)
    cipher = PendingTargetCipher(settings(), uuid4() if changed == "attempt" else attempt.id)
    if changed == "active":
        cipher = TargetCipher(settings())
    value = attempt.pending_target_encrypted
    if changed == "tamper":
        value = value[:-1] + bytes([value[-1] ^ 1])
    with pytest.raises(ServiceUnavailableError):
        cipher.decrypt(
            value,
            attempt.pending_target_key_id,
            uuid4() if changed == "owner" else users[0].id,
            uuid4() if changed == "version" else row.id,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("Country", {"Code3": "USA"}),
        ("Region", {"Code": "KA"}),
        ("Locality", "Delhi"),
        ("PostalCode", "302099"),
        ("PostalCode", None),
    ],
)
async def test_structural_disagreement_never_retained(case, field, value):
    db, _, _, _, geo = case
    row = await eligible(case)
    item = result()
    item["Address"].update(Street="Other Road")
    item["Address"][field] = value
    geo.confirm_area.return_value = precise_area_decision(ADDRESS.model_dump(), [item])
    _, challenge, _ = await check(case, row.id)
    attempt = await db.get(Session, challenge.session_id)
    assert attempt.pending_target_encrypted is None and attempt.manual_review_status is None


@pytest.mark.parametrize("kind", ["poor", "stale", "mock", "unstable"])
async def test_bad_gps_has_no_pending_target_or_provider_call(case, kind):
    db, users, svc, clock, geo = case
    row = await eligible(case)
    challenge = await svc.start(users[0].id, row.id)
    values = samples(clock[0])
    if kind == "poor":
        values[0].accuracy_m = 51
    elif kind == "stale":
        values[0].timestamp -= timedelta(seconds=10)
    elif kind == "mock":
        values[0].mock_location = True
    else:
        values[0].latitude = 1
    clock[0] += timedelta(seconds=33)
    await svc.finish(
        users[0].id,
        challenge.session_id,
        LocationCompleteInput(challenge=challenge.challenge, samples=values),
    )
    assert not (await db.get(Session, challenge.session_id)).pending_target_encrypted
    geo.confirm_area.assert_not_awaited()


@pytest.mark.parametrize(
    "kind", ["absent", "unreviewed", "replaced", "deleted", "expired", "mismatch"]
)
async def test_document_gate_is_backend_authoritative(case, kind):
    db, users, svc, _, _ = case
    row, attempt = await pending(case, document=kind != "absent")
    if kind in {"unreviewed", "mismatch"}:
        row.document_status = "NEEDS_REVIEW" if kind == "unreviewed" else "MISMATCH"
    elif kind == "replaced":
        svc.storage.etag = "replaced-synthetic-content"
    elif kind in {"deleted", "expired"}:
        from app.models.user_document import UserDocument

        doc = await db.get(UserDocument, row.document_id)
        if kind == "deleted":
            doc.deleted_at = NOW
        else:
            doc.expires_at = NOW.date() - timedelta(days=1)
    await db.flush()
    with pytest.raises(ValidationAppError) as exc:
        await svc.resolve_manual_location(users[2].id, row.id, attempt.id, payload(users))
    assert exc.value.code == "ADDRESS_DOCUMENT_REQUIRED_FOR_MANUAL_LOCATION_APPROVAL"
    assert not attempt.counted_day and not await events(db, users[0].id)


async def test_approval_history_score_idempotency_and_fixed_later_checks(case):
    db, users, svc, clock, geo = case
    row, attempt = await pending(case, document=True)
    original = deepcopy(attempt.derived_evidence)
    provider = row.target_encrypted
    score = TrustScoreSnapshot(
        user_id=users[0].id, score_version="v2", status="available", overall_score=82
    )
    db.add(score)
    await db.flush()
    p = payload(users)
    receipt = await svc.resolve_manual_location(users[2].id, row.id, attempt.id, p)
    assert (
        row.target_encrypted != provider
        and row.target_source == "onsite_confirmation_manual_review"
    )
    assert row.geocode_metadata["provider_target_superseded"] and row.target_confirmed_at
    assert not attempt.pending_target_encrypted and not attempt.pending_target_key_id
    assert attempt.result == "NEEDS_REVIEW" and attempt.derived_evidence == original
    assert attempt.manual_review_status == "approved" and not row.completed_at
    state = await svc.state(users[0].id)
    assert state.successful_gps_checks == 1 and state.status != "PERMANENT_ADDRESS_VERIFIED"
    assert await svc.resolve_manual_location(users[2].id, row.id, attempt.id, p) == receipt
    assert (
        await svc.resolve_manual_location(users[2].id, row.id, attempt.id, payload(users))
        == receipt
    )
    assert len(await events(db, users[0].id)) == 1
    snapshots = list(
        (
            await db.scalars(
                select(TrustScoreSnapshot).where(TrustScoreSnapshot.user_id == users[0].id)
            )
        ).all()
    )
    assert len(snapshots) == 1 and snapshots[0].overall_score == 82
    assert "position" not in json.dumps((await events(db, users[0].id))[0].metadata_payload)
    locked = row.target_encrypted
    with pytest.raises(ConflictError):
        await svc.start(users[0].id, row.id)
    for day in (1, 2):
        clock[0] = NOW + timedelta(days=day)
        state, _, _ = await check(case, row.id)
        assert row.target_encrypted == locked and state.successful_gps_checks == day + 1
    geo.confirm_area.assert_awaited_once()


@pytest.mark.parametrize(
    "outcome,status",
    [
        ("REJECT_ONSITE_LOCATION", "rejected"),
        ("REQUEST_ADDRESS_CORRECTION", "correction_requested"),
        ("REQUEST_ADDITIONAL_EVIDENCE", "additional_evidence_requested"),
    ],
)
async def test_other_decisions_preserve_provider_and_progress(case, outcome, status):
    db, users, svc, _, _ = case
    row, attempt = await pending(case)
    provider, history = row.target_encrypted, deepcopy(attempt.derived_evidence)
    p = payload(users, outcome)
    receipt = await svc.resolve_manual_location(users[2].id, row.id, attempt.id, p)
    assert attempt.manual_review_status == status and attempt.derived_evidence == history
    assert row.target_encrypted == provider and not row.target_confirmed_at
    assert (await svc.state(users[0].id)).successful_gps_checks == 0
    assert bool(attempt.pending_target_encrypted) == (status == "additional_evidence_requested")
    assert await svc.resolve_manual_location(users[2].id, row.id, attempt.id, p) == receipt
    assert len(await events(db, users[0].id)) == 1
    if status != "additional_evidence_requested":
        with pytest.raises(ConflictError):
            await svc.resolve_manual_location(users[2].id, row.id, attempt.id, payload(users))


async def test_additional_evidence_requires_new_document_review(case):
    _, users, svc, _, _ = case
    row, attempt = await pending(case, document=True)
    await svc.resolve_manual_location(
        users[2].id, row.id, attempt.id, payload(users, "REQUEST_ADDITIONAL_EVIDENCE")
    )
    with pytest.raises(ValidationAppError):
        await svc.resolve_manual_location(users[2].id, row.id, attempt.id, payload(users))
    await svc.review(
        users[2].id,
        row.id,
        AddressReviewInput(
            document_id=row.document_id,
            outcome="MATCH",
            observed_address=ADDRESS,
        ),
    )
    await svc.resolve_manual_location(users[2].id, row.id, attempt.id, payload(users))
    assert (await svc.state(users[0].id)).successful_gps_checks == 1


async def test_material_edit_invalidates_and_clears_pending(case):
    _, users, svc, _, _ = case
    row, attempt = await pending(case, document=True)
    history = deepcopy(attempt.derived_evidence)
    await svc.save_address(
        users[0].id, ADDRESS.model_copy(update={"address_line_1": "124 Synthetic Road"})
    )
    assert attempt.manual_review_status == "invalidated" and not attempt.pending_target_encrypted
    assert attempt.derived_evidence == history
    with pytest.raises(NotFoundError):
        await svc.resolve_manual_location(users[2].id, row.id, attempt.id, payload(users))


async def test_historical_attempt_never_fabricated(case):
    from tests.test_permanent_address_retry_resolution import failed

    _, users, svc, _, _ = case
    row, attempt, _ = await failed(case)
    view = await svc.manual_location_detail(users[2].id, row.id, attempt.id)
    assert view["manual_review_status"] == "waiting_for_address_document"
    assert not view["pending_target_available"] and not view["approval_eligible"]
    with pytest.raises(ConflictError):
        await svc.resolve_manual_location(users[2].id, row.id, attempt.id, payload(users))


async def test_expired_original_cycle_not_retimed(case):
    _, users, svc, clock, _ = case
    row, attempt = await pending(case, document=True)
    clock[0] += timedelta(days=7)
    with pytest.raises(ConflictError):
        await svc.resolve_manual_location(users[2].id, row.id, attempt.id, payload(users))
    assert not attempt.counted_day


async def test_database_rejects_counted_unapproved_null_disposition(case):
    from tests.test_permanent_address_retry_resolution import failed

    db, _, _, _, _ = case
    _, attempt, _ = await failed(case)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            attempt.counted_day = NOW.date()
            await db.flush()


@pytest.mark.parametrize("kind", ["candidate", "hr", "inactive", "unverified", "self", "binding"])
async def test_admin_authorization_and_binding(case, kind):
    db, users, svc, _, _ = case
    row, attempt = await pending(case, document=True)
    reviewer = users[2]
    p = payload(users)
    if kind in {"candidate", "hr"}:
        reviewer.role = "user" if kind == "candidate" else "hr"
    elif kind == "inactive":
        reviewer.is_active = False
    elif kind == "unverified":
        reviewer.email_verified_at = None
    elif kind == "self":
        reviewer = users[0]
        reviewer.role, reviewer.email_verified_at = "admin", NOW
    else:
        p.candidate_id = users[1].id
    await db.flush()
    with pytest.raises(NotFoundError if kind == "binding" else ForbiddenError):
        await svc.resolve_manual_location(reviewer.id, row.id, attempt.id, p)


async def test_retry_resolution_cannot_bypass_pending_review(case):
    _, users, svc, _, _ = case
    row, attempt = await pending(case)
    with pytest.raises(ConflictError):
        await svc.resolve_location_review(
            users[2].id,
            row.id,
            attempt.id,
            LocationReviewResolutionInput(candidate_id=users[0].id, resolution="retry_allowed"),
        )


def test_dto_no_arbitrary_override():
    with pytest.raises(ValidationError):
        ManualLocationReviewInput(
            candidate_id=uuid4(), idempotency_key=uuid4(), outcome="MARK_PERMANENT_ADDRESS_VERIFIED"
        )
    with pytest.raises(ValidationError):
        ManualLocationReviewInput(
            candidate_id=uuid4(),
            idempotency_key=uuid4(),
            outcome="APPROVE_ONSITE_LOCATION",
            position=[0, 0],
        )
    assert not manual_eligible({"accepted": False, "reason": "no_result"})


def test_manual_policy_never_joins_components_or_accepts_broad_estimated_results():
    item = result()
    item["Address"]["Street"] = "Other Synthetic Road"
    for change in ({"PlaceType": "Street"}, {"EstimatedPointAddress": True}):
        assert not manual_eligible(
            precise_area_decision(ADDRESS.model_dump(), [{**item, **change}])
        )
    first, second = deepcopy(item), deepcopy(item)
    first["Address"]["Locality"] = "Delhi"
    second["Address"]["PostalCode"] = "302099"
    assert not manual_eligible(precise_area_decision(ADDRESS.model_dump(), [first, second]))


async def test_manual_fixed_target_uses_unchanged_75m_radius(case):
    _, users, svc, clock, geo = case
    row, attempt = await pending(case, document=True)
    await svc.resolve_manual_location(users[2].id, row.id, attempt.id, payload(users))
    locked = row.target_encrypted
    clock[0] = NOW + timedelta(days=1)
    challenge = await svc.start(users[0].id, row.id)
    values = samples(clock[0])
    for sample in values:
        sample.latitude = 0.00072
    clock[0] += timedelta(seconds=33)
    state = await svc.finish(
        users[0].id,
        challenge.session_id,
        LocationCompleteInput(challenge=challenge.challenge, samples=values),
    )
    assert state.last_location_result == "OUTSIDE_EXPECTED_AREA"
    assert state.successful_gps_checks == 1 and row.target_encrypted == locked
    geo.confirm_area.assert_awaited_once()


async def test_routes_auth_no_store_and_document_error(case):
    from app.api.v1.routes.permanent_address import service
    from app.auth.deps import CurrentUser, get_current_user
    from app.main import app

    _, users, svc, _, _ = case
    row, attempt = await pending(case)
    path = f"/api/v1/permanent-address/location-reviews/{row.id}/sessions/{attempt.id}"
    try:
        app.dependency_overrides[service] = lambda: svc
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get(path)).status_code == 401
            for role in ("user", "hr"):
                app.dependency_overrides[get_current_user] = lambda role=role: CurrentUser(
                    id=users[0].id, email="qa@example.test", role=role
                )
                assert (await client.get(path)).status_code == 403
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(
                id=users[2].id, email="admin@example.test", role="admin"
            )
            response = await client.get(path)
            assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
            assert "position" not in response.text and "encrypted" not in response.text
            response = await client.post(
                path + "/resolution", json=payload(users).model_dump(mode="json")
            )
            assert response.status_code == 400
            assert (
                response.json()["error"]["code"]
                == "ADDRESS_DOCUMENT_REQUIRED_FOR_MANUAL_LOCATION_APPROVAL"
            )
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("race", ["duplicate", "reject", "edit", "start"])
async def test_real_transactions_serialize_decisions(race):
    users = []
    user_ids = []
    async with AsyncSession(engine, expire_on_commit=False) as db:
        try:
            users = [
                User(email=f"{uuid4()}@example.test", role="user", is_active=True) for _ in range(3)
            ]
            db.add_all(users)
            await db.commit()
            user_ids = [user.id for user in users]
            clock = [NOW.replace(year=2076)]
            svc = PermanentAddressService(
                db,
                settings(),
                geocoder=FakeGeocoder(),
                clock=lambda: clock[0],
                storage=FakeStorage(),
            )
            row, attempt = await pending((db, users, svc, clock, svc.geocoder), document=True)
            await db.commit()
            owner, admin, version, sid = users[0].id, users[2].id, row.id, attempt.id
            p = payload(users)

            async def operation(kind):
                async with AsyncSession(engine, expire_on_commit=False) as session:
                    service = PermanentAddressService(
                        session,
                        settings(),
                        geocoder=FakeGeocoder(),
                        clock=lambda: clock[0],
                        storage=FakeStorage(),
                    )
                    try:
                        if kind == "edit":
                            await service.save_address(
                                owner,
                                ADDRESS.model_copy(update={"address_line_1": "125 Synthetic Road"}),
                            )
                        elif kind == "start":
                            await service.start(owner, version)
                        else:
                            command = (
                                p
                                if kind == "approve"
                                else p.model_copy(
                                    update={
                                        "idempotency_key": uuid4(),
                                        "outcome": "REJECT_ONSITE_LOCATION",
                                    }
                                )
                            )
                            await service.resolve_manual_location(admin, version, sid, command)
                        return "ok"
                    except (ConflictError, NotFoundError):
                        await session.rollback()
                        return "blocked"

            outcomes = await asyncio.wait_for(
                asyncio.gather(
                    operation("approve"), operation("approve" if race == "duplicate" else race)
                ),
                timeout=15,
            )
            await db.refresh(attempt)
            assert len(await events(db, owner)) <= 1
            if race == "duplicate":
                assert outcomes == ["ok", "ok"] and attempt.counted_day
            elif race == "reject":
                assert sorted(outcomes) == ["blocked", "ok"]
            elif race == "start":
                assert outcomes == ["ok", "blocked"]
            else:
                assert outcomes[1] == "ok" and not attempt.pending_target_encrypted
            assert attempt.result == "NEEDS_REVIEW"
        finally:
            await db.rollback()
            for user_id in user_ids:
                await db.execute(delete(User).where(User.id == user_id))
            await db.execute(delete(Budget).where(Budget.month == "2076-10"))
            await db.commit()
