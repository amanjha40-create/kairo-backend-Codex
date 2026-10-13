import json
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import select

from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.permanent_address import PermanentAddressSession as Session
from app.models.trust_score_snapshot import TrustScoreSnapshot
from app.models.user_account_event import UserAccountEvent
from app.schemas.permanent_address import LocationReviewResolutionInput
from tests.test_permanent_address_onsite import eligible
from tests.test_permanent_address_verification import NOW, check
from tests.test_permanent_address_verification import case as case


async def failed(case):
    db, users, svc, _, geo = case
    row = await eligible(case)
    geo.confirm_area.return_value = {
        "accepted": False,
        "reason": "unsupported_precision",
        "diagnostics": {
            "reverse_place_type": "Street",
            "street_decision_reason": "street_conflict",
        },
    }
    _, challenge, _ = await check(case, row.id)
    users[2].role = "admin"
    users[2].email_verified_at = NOW
    await db.flush()
    attempt = await db.get(Session, challenge.session_id)
    return (
        row,
        attempt,
        LocationReviewResolutionInput(candidate_id=users[0].id, resolution="retry_allowed"),
    )


async def audit_events(db, user_id):
    return list(
        (
            await db.scalars(
                select(UserAccountEvent).where(
                    UserAccountEvent.user_id == user_id,
                    UserAccountEvent.event_type == "permanent_address_retry_allowed",
                )
            )
        ).all()
    )


async def test_resolution_preserves_history_target_progress_score_and_audits_once(case):
    db, users, svc, clock, geo = case
    row, attempt, payload = await failed(case)
    original = deepcopy(attempt.derived_evidence)
    target = (row.target_encrypted, row.target_key_id, deepcopy(row.geocode_metadata))
    address = (row.address_hash, deepcopy(row.claimed_address), row.version)
    snapshot = TrustScoreSnapshot(
        user_id=users[0].id, score_version="v2", status="available", overall_score=82
    )
    db.add(snapshot)
    await db.flush()
    geo.confirm_area.reset_mock()
    resolution = await svc.resolve_location_review(users[2].id, row.id, attempt.id, payload)
    assert resolution["reviewer_id"] == str(users[2].id)
    assert resolution["reviewed_at"] == clock[0].isoformat()
    assert resolution["resolution"] == "retry_allowed"
    assert attempt.result == "NEEDS_REVIEW" and attempt.counted_day is None
    assert attempt.derived_evidence == {**original, "review_resolution": resolution}
    assert (row.target_encrypted, row.target_key_id, row.geocode_metadata) == target
    assert (row.address_hash, row.claimed_address, row.version) == address
    assert row.target_source == "provider_geocode" and row.target_confirmed_at is None
    state = await svc.state(users[0].id)
    assert state.successful_gps_checks == 0 and state.required_gps_checks == 3
    assert state.can_start_location and state.target_confirmation_required
    assert state.last_location_result == "NEEDS_REVIEW"
    assert row.document_status == "REQUIRED" and row.completed_at is None
    events = await audit_events(db, users[0].id)
    assert len(events) == 1 and str(events[0].id) == resolution["audit_event_id"]
    assert events[0].actor_user_id == users[2].id
    assert events[0].metadata_payload == {
        "address_version_id": str(row.id),
        "session_id": str(attempt.id),
        "resolution": "retry_allowed",
        "previous_result": "NEEDS_REVIEW",
    }
    for forbidden in ("Synthetic Road", "302020", "latitude", "longitude", "position"):
        assert forbidden not in json.dumps(events[0].metadata_payload)
    assert await svc.resolve_location_review(users[2].id, row.id, attempt.id, payload) == resolution
    assert len(await audit_events(db, users[0].id)) == 1
    scores = list(
        (
            await db.scalars(
                select(TrustScoreSnapshot).where(
                    TrustScoreSnapshot.user_id == users[0].id,
                )
            )
        ).all()
    )
    assert len(scores) == 1 and scores[0].id == snapshot.id and scores[0].overall_score == 82
    geo.confirm_area.assert_not_awaited()
    assert geo.calls == 1
    assert (await svc.start(users[0].id, row.id)).session_id != attempt.id


async def test_replay_cannot_rearm_a_later_failed_attempt(case):
    db, users, svc, _, _ = case
    row, attempt, payload = await failed(case)
    receipt = await svc.resolve_location_review(users[2].id, row.id, attempt.id, payload)
    await check(case, row.id)
    assert row.target_status == "needs_review"
    assert await svc.resolve_location_review(users[2].id, row.id, attempt.id, payload) == receipt
    assert row.target_status == "needs_review"
    assert not (await svc.state(users[0].id)).can_start_location
    assert len(await audit_events(db, users[0].id)) == 1


@pytest.mark.parametrize("kind", ["candidate", "hr", "inactive", "unverified", "missing", "self"])
async def test_unauthorized_reviewer_rejected(case, kind):
    db, users, svc, _, _ = case
    row, attempt, payload = await failed(case)
    reviewer = users[2]
    if kind in {"candidate", "hr"}:
        reviewer.role = "user" if kind == "candidate" else "hr"
    elif kind == "inactive":
        reviewer.is_active = False
    elif kind == "unverified":
        reviewer.email_verified_at = None
    elif kind == "self":
        reviewer = users[0]
        reviewer.role, reviewer.email_verified_at = "admin", NOW
    await db.flush()
    with pytest.raises(ForbiddenError):
        await svc.resolve_location_review(
            uuid4() if kind == "missing" else reviewer.id, row.id, attempt.id, payload
        )
    assert row.target_status == "needs_review"
    assert not await audit_events(db, users[0].id)


@pytest.mark.parametrize("kind", ["owner", "version", "attempt"])
async def test_wrong_binding_rejected(case, kind):
    db, users, svc, _, _ = case
    row, attempt, payload = await failed(case)
    if kind == "owner":
        payload.candidate_id = users[1].id
    with pytest.raises(NotFoundError):
        await svc.resolve_location_review(
            users[2].id,
            uuid4() if kind == "version" else row.id,
            uuid4() if kind == "attempt" else attempt.id,
            payload,
        )
    assert not await audit_events(db, users[0].id)


@pytest.mark.parametrize(
    "kind",
    [
        "matched",
        "open",
        "cycle",
        "counted",
        "confirmed",
        "onsite",
        "ready",
        "no_target",
        "completed",
        "country",
        "newer",
    ],
)
async def test_non_reviewable_state_rejected(case, kind):
    db, users, svc, _, _ = case
    row, attempt, payload = await failed(case)
    if kind == "matched":
        attempt.result = "MATCHED"
    elif kind == "open":
        attempt.completed_at = None
    elif kind == "cycle":
        row.cycle += 1
    elif kind == "counted":
        db.add(
            Session(
                address_version_id=row.id,
                cycle=row.cycle,
                challenge_hash="a" * 64,
                started_at=NOW - timedelta(days=1),
                expires_at=NOW,
                completed_at=NOW,
                result="MATCHED",
                counted_day=NOW.date(),
            )
        )
    elif kind == "confirmed":
        row.target_confirmed_at = NOW
    elif kind == "onsite":
        row.target_source = "onsite_confirmation"
    elif kind == "ready":
        row.target_status = "confirmation_required"
    elif kind == "no_target":
        row.target_encrypted = None
    elif kind == "completed":
        row.completed_at = NOW
    elif kind == "country":
        row.claimed_address = {**row.claimed_address, "country": "US"}
    else:
        row.target_status = "confirmation_required"
        await check(case, row.id)
    await db.flush()
    with pytest.raises(ConflictError):
        await svc.resolve_location_review(users[2].id, row.id, attempt.id, payload)
    assert "review_resolution" not in attempt.derived_evidence
    assert not await audit_events(db, users[0].id)


def test_only_retry_allowed_and_no_extra_fields():
    for resolution in ("verified", "pass", "MATCHED"):
        with pytest.raises(ValidationError):
            LocationReviewResolutionInput(candidate_id=uuid4(), resolution=resolution)
    with pytest.raises(ValidationError):
        LocationReviewResolutionInput(candidate_id=uuid4(), resolution="retry_allowed", progress=1)


async def test_route_auth_schema_and_private_response(case):
    from app.api.v1.routes.permanent_address import service
    from app.auth.deps import CurrentUser, get_current_user
    from app.main import app

    _, users, svc, _, _ = case
    row, attempt, payload = await failed(case)
    path = f"/api/v1/permanent-address/reviews/{row.id}/sessions/{attempt.id}/resolution"
    try:
        app.dependency_overrides[service] = lambda: svc
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (
                await client.post(path, json=payload.model_dump(mode="json"))
            ).status_code == 401
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(
                id=users[0].id, email="qa@example.test", role="user"
            )
            assert (
                await client.post(path, json=payload.model_dump(mode="json"))
            ).status_code == 403
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(
                id=users[2].id, email="reviewer@example.test", role="admin"
            )
            response = await client.post(path, json=payload.model_dump(mode="json"))
            assert response.status_code == 200
            assert "no-store" in response.headers["cache-control"]
            assert set(response.json()) == {
                "resolution",
                "reviewed_at",
                "reviewer_id",
                "audit_event_id",
            }
    finally:
        app.dependency_overrides.clear()
