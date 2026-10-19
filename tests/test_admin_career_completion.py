"""Admin-only canonical Career adapters: persistence, isolation and provenance."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import select

from app.admin_operations.enums import ProfileProvenanceSource
from app.auth.deps import CurrentUser, get_current_user
from app.config import get_settings
from app.db.session import async_session_factory
from app.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.main import app
from app.models.admin_profile_provenance import AdminProfileProvenance
from app.models.user import User
from app.schemas.admin_operations import AdminCareerMutationRequest, AdminCareerUpdateRequest
from app.schemas.passport_share import PassportSharePermissions
from app.services import admin_career_records
from app.services.admin_operations_service import AdminOperationsService
from app.services.public_passport_service import PublicPassportService
from app.services.resume_review_service import ResumeReviewService

CASES = {
    "portfolio": (
        {"title": "Synthetic portfolio", "tags": ["Design"], "url": "https://example.com/"},
        {"description": "Updated", "tags": ["Updated"]},
        {"description": None},
    ),
    "project": (
        {
            "title": "Synthetic project",
            "role": "Engineer",
            "start_date": "2020-01-01",
            "end_date": "2021-01-01",
            "repository_url": "https://example.com/repo",
        },
        {"role": "Lead"},
        {"role": None},
    ),
    "skill": ({"name": "  Python   development "}, {"name": "  SQL   development "}, None),
    "gig_platform": (
        {
            "platform_name": "Synthetic",
            "partner_role": "Contributor",
            "started_at": "2020-01-01",
            "rating": "4.25",
        },
        {"partner_id": "synthetic-id"},
        {"partner_id": None},
    ),
}


async def seed(session):
    actor = User(email=f"admin-{uuid4()}@example.com", role="admin", is_active=True)
    user = User(
        email=f"candidate-{uuid4()}@example.com",
        full_name="Synthetic Candidate",
        role="user",
        is_active=True,
        admin_created_at=datetime.now(UTC),
    )
    session.add_all([actor, user])
    await session.commit()
    return actor, user


@pytest.mark.parametrize("kind", CASES)
async def test_canonical_lifecycle_and_append_only_provenance(kind):
    create, update, clear = CASES[kind]
    async with async_session_factory() as session:
        actor, user = await seed(session)
        service = AdminOperationsService(session, get_settings())
        result = await service.mutate_candidate_career(
            actor.id,
            user.id,
            AdminCareerMutationRequest(
                claim_type=kind, payload=create, source=ProfileProvenanceSource.CV_EXTRACTED
            ),
        )
        record_id = result.record_id
        before = list(
            (
                await session.scalars(
                    select(AdminProfileProvenance).where(
                        AdminProfileProvenance.record_id == record_id
                    )
                )
            ).all()
        )
        assert before and all(
            p.source == "cv_extracted" and p.candidate_confirmed_at is None for p in before
        )
        await service.mutate_candidate_career(
            actor.id,
            user.id,
            AdminCareerUpdateRequest(claim_type=kind, payload=update),
            record_id=record_id,
        )
        read = await service.read_candidate_career(user.id, kind, record_id)
        assert read.record.verification_status in {"pending", "self_declared"}
        for field, value in update.items():
            assert getattr(read.record, field) == (
                " ".join(value.split()) if kind == "skill" else value
            )
        if clear:
            await service.mutate_candidate_career(
                actor.id,
                user.id,
                AdminCareerUpdateRequest(claim_type=kind, payload=clear),
                record_id=record_id,
            )
            read = await service.read_candidate_career(user.id, kind, record_id)
            assert getattr(read.record, next(iter(clear))) is None
            latest = await service._latest_provenance(user.id, kind, record_id, next(iter(clear)))
            assert latest.source == "admin_entered" and latest.value_hash == service._value_hash(
                None
            )
        for p in before:
            assert (await session.get(AdminProfileProvenance, p.id)).source == "cv_extracted"
        serialized = read.model_dump_json()
        public = await PublicPassportService(session, get_settings()).build_vault_for_user(
            user.id,
            PassportSharePermissions(include_projects=True, include_skills=True),
            public_only=True,
        )
        for private in (
            "value_hash",
            "actor_user_id",
            "admin_entered",
            "cv_extracted",
            "object_key",
        ):
            assert private not in serialized
            assert private not in public.model_dump_json()
        await service.delete_candidate_career(actor.id, user.id, kind, record_id)
        with pytest.raises(NotFoundError):
            await service.read_candidate_career(user.id, kind, record_id)
        assert await session.get(admin_career_records.MODELS[kind], record_id) is not None


@pytest.mark.parametrize("kind", CASES)
async def test_protected_and_cross_candidate_writes_denied(kind):
    create, update, _ = CASES[kind]
    async with async_session_factory() as session:
        actor, user = await seed(session)
        _, other = await seed(session)
        service = AdminOperationsService(session, get_settings())
        result = await service.mutate_candidate_career(
            actor.id, user.id, AdminCareerMutationRequest(claim_type=kind, payload=create)
        )
        with pytest.raises(NotFoundError):
            await service.mutate_candidate_career(
                actor.id,
                other.id,
                AdminCareerUpdateRequest(claim_type=kind, payload=update),
                record_id=result.record_id,
            )
        with pytest.raises(NotFoundError):
            await service.read_candidate_career(other.id, kind, result.record_id)
        with pytest.raises(NotFoundError):
            await service.delete_candidate_career(actor.id, other.id, kind, result.record_id)
        record = await session.get(admin_career_records.MODELS[kind], result.record_id)
        record.verification_status = "verified"
        await session.commit()
        with pytest.raises(ConflictError):
            await service.mutate_candidate_career(
                actor.id,
                user.id,
                AdminCareerUpdateRequest(claim_type=kind, payload=update),
                record_id=result.record_id,
            )
        with pytest.raises(ConflictError):
            await service.delete_candidate_career(actor.id, user.id, kind, result.record_id)
        assert record.verification_status == "verified" and record.deleted_at is None


async def test_skill_duplicate_rename_and_merged_dates():
    async with async_session_factory() as session:
        actor, user = await seed(session)
        service = AdminOperationsService(session, get_settings())
        result = await service.mutate_candidate_career(
            actor.id,
            user.id,
            AdminCareerMutationRequest(claim_type="skill", payload={"name": "Python"}),
        )
        with pytest.raises(ConflictError):
            await service.mutate_candidate_career(
                actor.id,
                user.id,
                AdminCareerMutationRequest(claim_type="skill", payload={"name": "  PYTHON "}),
            )
        await service.mutate_candidate_career(
            actor.id,
            user.id,
            AdminCareerUpdateRequest(claim_type="skill", payload={"name": "SQL"}),
            record_id=result.record_id,
        )
        assert (
            await session.get(admin_career_records.MODELS["skill"], result.record_id)
        ).normalized_name == "sql"
        for kind in ("project", "gig_platform"):
            result = await service.mutate_candidate_career(
                actor.id,
                user.id,
                AdminCareerMutationRequest(claim_type=kind, payload=CASES[kind][0]),
            )
            field = "end_date" if kind == "project" else "ended_at"
            with pytest.raises(ValidationAppError):
                await service.mutate_candidate_career(
                    actor.id,
                    user.id,
                    AdminCareerUpdateRequest(claim_type=kind, payload={field: "2019-01-01"}),
                    record_id=result.record_id,
                )


@pytest.mark.parametrize("kind", CASES)
def test_unknown_fields_and_missing_required_rejected(kind):
    with pytest.raises(ValidationError):
        AdminCareerMutationRequest(claim_type=kind, payload={})
    with pytest.raises(ValidationError):
        AdminCareerMutationRequest(
            claim_type=kind, payload={**CASES[kind][0], "verification_status": "verified"}
        )
    with pytest.raises(ValidationError):
        AdminCareerUpdateRequest(claim_type=kind, payload={})


@pytest.mark.parametrize("kind", CASES)
@pytest.mark.parametrize("role", [None, "user", "hr", "institution"])
async def test_non_admin_routes_denied(kind, role):
    if role:
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=uuid4(), email="test@example.com", role=role
        )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            root = f"/api/v1/admin/operations/candidates/{uuid4()}/career"
            for method, url, kwargs in [
                ("POST", root, {"json": {"claim_type": kind, "payload": CASES[kind][0]}}),
                (
                    "PATCH",
                    root + f"/{uuid4()}",
                    {"json": {"claim_type": kind, "payload": CASES[kind][1]}},
                ),
                ("GET", root + f"/{uuid4()}?claim_type={kind}", {}),
                ("GET", root + f"?claim_type={kind}", {}),
                ("DELETE", root + f"/{uuid4()}?claim_type={kind}", {}),
            ]:
                response = await client.request(method, url, **kwargs)
                assert response.status_code == (403 if role else 401), response.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_openapi_nine_types_and_canonical_payload_truth():
    schema = app.openapi()
    request = schema["components"]["schemas"]["AdminCareerMutationRequest"]
    assert len(request["properties"]["claim_type"]["enum"]) == 9
    assert len(request["allOf"]) == 4
    for condition in request["allOf"]:
        assert condition["then"]["properties"]["payload"]["additionalProperties"] is False


@pytest.mark.parametrize(
    "kind,payload,field",
    [
        (
            "employment",
            {"company_name": "Synthetic company", "role_title": "Engineer"},
            "role_title",
        ),
        ("education", {"institution_name": "Synthetic school", "degree": "Degree"}, "degree"),
        ("internship", {"company_name": "Synthetic company", "role": "Intern"}, "role"),
        (
            "freelance",
            {"client_name": "Synthetic client", "project_title": "Project"},
            "project_title",
        ),
        (
            "certification",
            {"title": "Certificate", "issuing_organization": "Synthetic issuer"},
            "title",
        ),
    ],
)
async def test_legacy_five_types_still_create_and_update(kind, payload, field):
    async with async_session_factory() as session:
        actor, user = await seed(session)
        service = AdminOperationsService(session, get_settings())
        created = await service.mutate_candidate_career(
            actor.id, user.id, AdminCareerMutationRequest(claim_type=kind, payload=payload)
        )
        updated = await service.mutate_candidate_career(
            actor.id,
            user.id,
            AdminCareerUpdateRequest(claim_type=kind, payload={**payload, field: "Updated"}),
            record_id=created.record_id,
        )
        assert created.record_id == updated.record_id
        record = await ResumeReviewService(session)._target(user.id, kind, created.record_id)
        assert record is not None


@pytest.mark.parametrize("kind", CASES)
async def test_admin_http_allowed_and_source_verified_field_guard(kind):
    async with async_session_factory() as session:
        actor, user = await seed(session)
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=actor.id, email=actor.email, role="admin"
        )
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                root = f"/api/v1/admin/operations/candidates/{user.id}/career"
                response = await client.post(
                    root, json={"claim_type": kind, "payload": CASES[kind][0]}
                )
                assert response.status_code == 201, response.text
                record_id = response.json()["record_id"]
                response = await client.patch(
                    root + "/" + record_id, json={"claim_type": kind, "payload": CASES[kind][1]}
                )
                assert response.status_code == 200, response.text
                response = await client.get(root + "/" + record_id, params={"claim_type": kind})
                assert response.status_code == 200, response.text
                listing = await client.get(root, params={"claim_type": kind})
                assert listing.status_code == 200, listing.text
                assert listing.json()["total"] == 1
                assert listing.json()["items"][0]["record"]["id"] == record_id
                response = await client.delete(root + "/" + record_id, params={"claim_type": kind})
                assert response.status_code == 200, response.text
        finally:
            app.dependency_overrides.pop(get_current_user, None)
        service = AdminOperationsService(session, get_settings())
        created = await service.mutate_candidate_career(
            actor.id,
            user.id,
            AdminCareerMutationRequest(
                claim_type=kind,
                payload={**CASES[kind][0], **({"name": "Other skill"} if kind == "skill" else {})},
            ),
        )
        field = next(iter(CASES[kind][1]))
        session.add(
            AdminProfileProvenance(
                user_id=user.id,
                record_type=kind,
                record_id=created.record_id,
                field_name=field,
                source="source_verified",
                actor_user_id=actor.id,
            )
        )
        await session.commit()
        with pytest.raises(ConflictError):
            await service.mutate_candidate_career(
                actor.id,
                user.id,
                AdminCareerUpdateRequest(claim_type=kind, payload=CASES[kind][1]),
                record_id=created.record_id,
            )
        with pytest.raises(ConflictError):
            await service.delete_candidate_career(actor.id, user.id, kind, created.record_id)
