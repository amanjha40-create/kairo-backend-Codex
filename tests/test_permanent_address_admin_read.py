"""Synthetic local projections; never invoke live GPS, provider or storage."""

from datetime import timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select, text

from app.exceptions import ForbiddenError, NotFoundError
from app.models.trust_score_snapshot import TrustScoreSnapshot
from app.schemas.permanent_address import AddressReviewInput
from app.services.permanent_address_admin import PermanentAddressAdminRead
from tests.test_permanent_address_documents import decision, upload
from tests.test_permanent_address_documents import no_storage_network as no_storage_network
from tests.test_permanent_address_manual_review import pending
from tests.test_permanent_address_verification import ADDRESS, NOW, check, evidence, prepare
from tests.test_permanent_address_verification import case as case


async def view(case, **kwargs):
    _, users, svc, *_ = case
    return await PermanentAddressAdminRead(svc).detail(users[2].id, users[0].id, **kwargs)


async def test_required_no_document_is_discoverable(case):
    _, users, svc, *_ = case
    version = await prepare(case)
    response = await view(case, address_version_id=version)
    assert response.document.present is False
    assert response.document.review_state == "REQUIRED"
    assert response.permanent_address.document_status == "REQUIRED"
    assert response.permanent_address.successful_location_checks == 0
    assert response.permanent_address.required_location_checks == 3
    assert not response.document.preview_available
    page = await PermanentAddressAdminRead(svc).discover(users[2].id, candidate_id=users[0].id)
    assert [s.address_version_id for s in page.items] == [version]


async def test_not_started_explicit_not_404(case):
    response = await view(case)
    assert response.permanent_address.overall_status == "NOT_STARTED"
    assert response.claimed_address is None
    assert response.document.review_state == "REQUIRED"


@pytest.mark.parametrize(
    "complete,submit,expected",
    [
        (False, False, "UPLOADING"),
        (True, False, "UPLOADED"),
        (True, True, "UNDER_REVIEW"),
    ],
)
async def test_upload_states(case, complete, submit, expected):
    await upload(case, complete=complete, submit=submit)
    response = await view(case)
    assert response.document.present
    assert response.document.review_state == expected
    assert response.document.preview_available is submit


@pytest.mark.parametrize(
    "outcome,expected",
    [
        ("APPROVE_MATCHING", "MATCH"),
        ("REJECT", "REJECTED"),
        ("REQUEST_CORRECTION", "NEEDS_CORRECTION"),
        ("REQUEST_DIFFERENT_DOCUMENT", "NEEDS_CORRECTION"),
    ],
)
async def test_document_review_truth(case, outcome, expected):
    _, users, svc, *_ = case
    version, intent, _ = await upload(case)
    await svc.decide_address_document(users[2].id, version, decision(intent.document_id, outcome))
    response = await view(case)
    assert response.document.review_state == expected
    assert response.document.reviewed_at
    assert response.permanent_address.successful_location_checks == 0
    assert response.permanent_address.overall_status != "PERMANENT_ADDRESS_VERIFIED"


@pytest.mark.parametrize("count", [0, 1, 2, 3])
@pytest.mark.parametrize("approved", [False, True])
async def test_progress_and_overall_reuse_canonical_truth(case, count, approved):
    _, users, svc, clock, _ = case
    version = await prepare(case)
    if approved:
        doc = await evidence(case, version)
        await svc.review(
            users[2].id,
            version,
            AddressReviewInput(document_id=doc.id, outcome="MATCH", observed_address=ADDRESS),
        )
    for day in range(count):
        clock[0] = NOW + timedelta(days=day)
        await check(case, version)
    before = await svc.state(users[0].id)
    response = await view(case)
    assert response.permanent_address.successful_location_checks == count
    assert response.permanent_address.overall_status == before.status
    assert (response.permanent_address.overall_status == "PERMANENT_ADDRESS_VERIFIED") is (
        approved and count == 3
    )
    assert (await svc.state(users[0].id)) == before


@pytest.mark.parametrize("document", [False, True])
async def test_manual_pending_document_gate_and_privacy(case, document):
    row, attempt = await pending(case, document=document)
    response = await view(case)
    s = response.permanent_address
    assert s.successful_location_checks == 0
    assert s.overall_status == "NEEDS_REVIEW"
    assert s.pending_manual_review_target_available is True
    assert s.manual_location_approval_eligible is document
    assert s.manual_review_status == ("pending" if document else "waiting_for_address_document")
    assert response.latest_attempt.session_id == attempt.id
    encoded = response.model_dump_json()
    for key in [
        "latitude",
        "longitude",
        "target_encrypted",
        "target_key_id",
        "object_key",
        "evidence_binding",
        "provider_address",
        "challenge_hash",
        "raw_samples",
    ]:
        assert key not in encoded
    assert str(row.target_encrypted) not in encoded


async def test_failed_attempt_does_not_count(case):
    _, attempt = await pending(case)
    assert attempt.result == "NEEDS_REVIEW" and attempt.counted_day is None
    assert (await view(case)).permanent_address.successful_location_checks == 0


async def test_stale_and_cross_candidate_version_rejected(case):
    _, users, svc, *_ = case
    version = await prepare(case)
    with pytest.raises(NotFoundError):
        await PermanentAddressAdminRead(svc).detail(
            users[2].id, users[1].id, address_version_id=version
        )
    await svc.save_address(users[0].id, ADDRESS.model_copy(update={"city": "Synthetic City"}))
    with pytest.raises(NotFoundError):
        await view(case, address_version_id=version)
    response = await view(case)
    assert response.document.review_state == "REQUIRED"
    assert response.versions[0].current and not response.versions[1].current


@pytest.mark.parametrize(
    "role,active,verified",
    [
        ("user", True, True),
        ("hr", True, True),
        ("admin", False, True),
        ("admin", True, False),
    ],
)
async def test_persisted_authorization(case, role, active, verified):
    db, users, svc, *_ = case
    await prepare(case)
    users[2].role, users[2].is_active = role, active
    users[2].email_verified_at = NOW if verified else None
    await db.flush()
    with pytest.raises(ForbiddenError):
        await view(case)
    with pytest.raises(ForbiddenError):
        await PermanentAddressAdminRead(svc).discover(users[2].id)


async def test_self_and_unknown_candidate_denied(case):
    _, users, svc, *_ = case
    reader = PermanentAddressAdminRead(svc)
    for candidate in [users[2].id, uuid4()]:
        with pytest.raises(NotFoundError):
            await reader.detail(users[2].id, candidate)


async def test_read_has_no_dml_or_score_or_provider_side_effect(case):
    db, users, svc, _, geo = case
    await pending(case)
    await db.flush()
    before = await svc.state(users[0].id)
    snapshots = await db.scalar(select(func.count()).select_from(TrustScoreSnapshot))
    calls = geo.calls
    statements = []
    conn = await db.connection()

    def record(conn, cursor, statement, params, context, many):
        statements.append(statement.strip().split()[0].upper())

    event.listen(conn.sync_connection, "before_cursor_execute", record)
    try:
        await view(case)
        await PermanentAddressAdminRead(svc).discover(users[2].id, candidate_id=users[0].id)
    finally:
        event.remove(conn.sync_connection, "before_cursor_execute", record)
    assert set(statements) == {"SELECT"}
    assert geo.calls == calls
    assert (await svc.state(users[0].id)) == before
    assert await db.scalar(select(func.count()).select_from(TrustScoreSnapshot)) == snapshots


async def test_routes_permissions_binding_and_cache(case):
    from app.api.v1.routes.permanent_address import admin_read_service
    from app.auth.deps import CurrentUser, get_current_user
    from app.main import app

    _, users, svc, *_ = case
    version = await prepare(case)
    try:
        app.dependency_overrides[admin_read_service] = lambda: svc
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            path = f"/api/v1/permanent-address/admin/candidates/{users[0].id}"
            assert (await client.get(path)).status_code == 401
            for role in ("user", "hr"):
                app.dependency_overrides[get_current_user] = lambda role=role: CurrentUser(
                    id=users[0].id, email="synthetic@example.test", role=role
                )
                assert (await client.get(path)).status_code == 403
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(
                id=users[2].id, email="admin@example.test", role="admin"
            )
            result = await client.get(path, params={"address_version_id": str(version)})
            assert result.status_code == 200 and "no-store" in result.headers["cache-control"]
            assert (
                await client.get(path, params={"address_version_id": str(uuid4())})
            ).status_code == 404
            assert (
                await client.get("/api/v1/permanent-address/admin/reviews", params={"limit": 51})
            ).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_openapi_typed_read_only_addition():
    from app.main import app

    schema = app.openapi()
    for path, model in [
        ("/api/v1/permanent-address/admin/reviews", "AdminAddressDiscovery"),
        ("/api/v1/permanent-address/admin/candidates/{candidate_id}", "AdminAddressDetail"),
    ]:
        assert set(schema["paths"][path]) == {"get"}
        dto = schema["paths"][path]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
        assert dto["$ref"].endswith("/" + model)


async def test_admin_connection_is_read_only_repeatable_read(case):
    from app.api.v1.routes.permanent_address import admin_read_service

    _, _, svc, *_ = case
    dependency = admin_read_service(svc.settings)
    reader = await anext(dependency)
    try:
        assert await reader.db.scalar(text("SHOW transaction_read_only")) == "on"
        assert await reader.db.scalar(text("SHOW transaction_isolation")) == "repeatable read"
    finally:
        await dependency.aclose()


async def test_discovery_is_bounded_and_omits_private_address(case):
    _, users, svc, *_ = case
    await prepare(case)
    reader = PermanentAddressAdminRead(svc)
    page = await reader.discover(users[2].id, candidate_id=users[0].id, limit=1)
    assert len(page.items) == 1 and page.next_offset is None
    assert "claimed_address" not in page.model_dump_json()
    assert not (await reader.discover(users[2].id, candidate_id=users[0].id, offset=1)).items
    with pytest.raises(ValueError):
        await reader.discover(users[2].id, limit=51)
