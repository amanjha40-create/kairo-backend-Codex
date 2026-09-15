"""Disclosure policy, route validation and service privacy regressions; no live credentials."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.main import app
from app.models import Employment, Education, Certification, Project
from app.repositories.passport_share import PassportShareRepository
from app.schemas.passport_share import (
    PassportShareCreateRequest,
    PassportSharePermissions,
    PassportShareUpdateRequest,
)
from app.schemas.public_passport import PublicPassportTrustScore
from app.services.passport_sharing_policy import narrow_policy, resolve_policy, stored_v2
from app.services.passport_share_service import PassportShareService
from app.services.public_passport_service import PublicPassportService, safe_recipient_url


def snapshot(mode="verified_only", **permissions):
    request = PassportShareCreateRequest(
        label="Synthetic QA", sharing_mode=mode, permissions=permissions
    )
    return stored_v2(request.sharing_mode, request.permissions)


def test_default_snapshot_and_exact_legacy_defaults():
    new = PassportShareCreateRequest(label="  Job review  ")
    assert new.label == "Job review"
    assert new.sharing_mode == "verified_only"
    assert {key for key, value in new.permissions.model_dump().items() if value} == {
        "include_employments",
        "include_educations",
        "show_employer_names",
    }
    policy = resolve_policy(stored_v2(new.sharing_mode, new.permissions))
    assert (policy.version, policy.mode) == (2, "verified_only")
    legacy = resolve_policy({})
    assert (legacy.version, legacy.mode) == (1, "legacy_mixed")
    assert legacy.permissions == PassportSharePermissions()
    assert legacy.permissions.include_certifications and legacy.permissions.include_portfolio
    assert legacy.permissions.show_trust_score and legacy.permissions.include_profile


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"label": None},
        {"label": ""},
        {"label": " \t\n"},
        {"label": "a" * 121},
        {"label": "ok", "sharing_mode": "legacy_mixed"},
        {"label": "ok", "sharing_mode": "other"},
    ],
)
def test_invalid_creation(payload):
    with pytest.raises(ValidationError):
        PassportShareCreateRequest.model_validate(payload)


def test_explicit_mixed_shares_only_selected_categories():
    policy = resolve_policy(snapshot("verified_and_candidate_provided", include_projects=True))
    assert policy.mode == "verified_and_candidate_provided"
    assert policy.permissions.include_projects
    assert not policy.permissions.include_employments
    assert not policy.permissions.include_educations
    assert not policy.permissions.show_trust_score


@pytest.mark.parametrize(
    "permissions",
    [
        {"include_profile": True},
        {"show_photo": True},
        {"include_certifications": True},
        {"include_projects": True},
        {"include_skills": True},
        {"include_portfolio": True},
        {"include_internships": True},
        {"include_freelance": True},
        {"include_gig_platforms": True},
        {"include_user_documents": True},
        {"show_documents": "true"},
    ],
)
def test_verified_only_rejects_unsupported_or_malformed_controls(permissions):
    with pytest.raises(ValidationError):
        PassportShareCreateRequest(label="QA", permissions=permissions)


@pytest.mark.parametrize(
    "permissions",
    [{"show_photo": True}, {"include_user_documents": True}, {"include_portfolio": True}],
)
def test_mixed_impossible_controls_fail(permissions):
    with pytest.raises(ValidationError):
        PassportShareCreateRequest(
            label="QA", sharing_mode="verified_and_candidate_provided", permissions=permissions
        )


@pytest.mark.parametrize(
    "stored",
    [
        None,
        [],
        {"verified_only": None},
        {"verified_only": "false"},
        {"verified_only": 1},
        {"verified_only": False},
        {"sharing_mode": "unknown"},
    ],
)
def test_marked_invalid_policy_never_becomes_legacy(stored):
    with pytest.raises(NotFoundError):
        resolve_policy(stored)


def test_invalid_complete_snapshot_fails_closed():
    values = snapshot()
    values["include_projects"] = True
    with pytest.raises(NotFoundError):
        resolve_policy(values)
    values = snapshot()
    values["show_photo"] = "false"
    with pytest.raises(NotFoundError):
        resolve_policy(values)


def test_partial_update_preserves_omitted_fields_and_legacy_null_reads():
    values = snapshot(
        "verified_and_candidate_provided",
        include_projects=True,
        include_profile=True,
        show_photo=True,
    )
    patched = narrow_policy(values, PassportShareUpdateRequest(permissions={"show_photo": False}))
    assert patched == {**values, "show_photo": False}
    assert narrow_policy(values, PassportShareUpdateRequest(label="Rename")) == values
    legacy = {"include_projects": True, "include_employments": False}
    updated = narrow_policy(
        legacy, PassportShareUpdateRequest(permissions={"include_projects": False})
    )
    assert "verified_only" not in updated
    assert not updated["include_employments"] and not updated["include_projects"]
    assert updated["include_portfolio"] == resolve_policy(legacy).permissions.include_portfolio


@pytest.mark.parametrize(
    "patch",
    [
        {"sharing_mode": "verified_and_candidate_provided"},
        {"permissions": {"show_trust_score": True}},
        {"permissions": {"include_profile": True}},
        {"permissions": {"show_photo": True}},
        {"permissions": {"show_documents": True}},
        {"permissions": {"include_projects": True}},
    ],
)
def test_link_expansion_requires_new_link(patch):
    with pytest.raises(ConflictError):
        narrow_policy(snapshot(), PassportShareUpdateRequest.model_validate(patch))


def test_mixed_to_verified_narrows_with_explicit_removal_of_ineligible_sections():
    values = snapshot(
        "verified_and_candidate_provided", include_employments=True, include_projects=True
    )
    result = narrow_policy(
        values,
        PassportShareUpdateRequest(
            sharing_mode="verified_only", permissions={"include_projects": False}
        ),
    )
    assert resolve_policy(result).mode == "verified_only"
    with pytest.raises(ValidationAppError):
        narrow_policy(values, PassportShareUpdateRequest(sharing_mode="verified_only"))


@pytest.mark.parametrize(
    "payload",
    [
        {"label": " "},
        {"label": ""},
        {"permissions": {"include_projects": None}},
        {"permissions": None},
        {"sharing_mode": None},
    ],
)
def test_invalid_patch(payload):
    with pytest.raises(ValidationError):
        PassportShareUpdateRequest.model_validate(payload)


class Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class Records:
    def __init__(self):
        self.queries = []
        self.rows = {
            Employment: [
                SimpleNamespace(
                    id=uuid4(),
                    employer_legal_name="Hidden Employer",
                    job_title="Role",
                    start_date=None,
                    end_date=None,
                    verification_method="contact",
                    verification_status=status,
                )
                for status in [
                    "verified",
                    "approved",
                    "draft",
                    "submitted",
                    "under_review",
                    "rejected",
                ]
            ],
            Education: [
                SimpleNamespace(
                    id=uuid4(),
                    institution_name="Hidden Institution",
                    degree=None,
                    field_of_study=None,
                    education_level=None,
                    grade=None,
                    start_date=None,
                    end_date=None,
                    start_date_precision=None,
                    end_date_precision=None,
                    is_currently_studying=False,
                    verification_status=status,
                )
                for status in ["verified", "pending", "draft", "rejected"]
            ],
            Certification: [
                SimpleNamespace(
                    id=uuid4(),
                    title="Uploaded Certificate",
                    issuing_organization=None,
                    issued_date=None,
                    expiry_date=None,
                    does_not_expire=True,
                    credential_id=None,
                    credential_url="https://private.s3.amazonaws.com/key",
                    verification_status="approved",
                )
            ],
            Project: [
                SimpleNamespace(
                    id=uuid4(),
                    title="Candidate Project",
                    role=None,
                    description=None,
                    start_date=None,
                    end_date=None,
                    is_ongoing=False,
                    project_url=None,
                    repository_url=None,
                    organization_name=None,
                    verification_status="verified",
                )
            ],
        }

    async def execute(self, statement):
        self.queries.append(statement)
        model = statement.column_descriptions[0].get("entity")
        rows = self.rows.get(model, [])
        for criterion in statement._where_criteria:
            if str(criterion.left).endswith("verification_status"):
                rows = [row for row in rows if row.verification_status in criterion.right.value]
        return Result(rows)


def public_service(values):
    records = Records()
    service = PublicPassportService(records, SimpleNamespace())
    link = SimpleNamespace(
        id=uuid4(),
        owner_user_id=uuid4(),
        permissions=values,
        revoked_at=None,
        expires_at=None,
        label="QA",
        track_views=True,
    )
    service._shares = SimpleNamespace(get_by_token_hash=AsyncMock(return_value=link))
    service._users = SimpleNamespace(
        get_public_profile=AsyncMock(
            return_value=SimpleNamespace(
                full_name="QA Owner",
                headline="Private headline",
                location="Private location",
                profile_slug="private-slug",
                avatar_url="https://private.s3.amazonaws.com/photo",
            )
        )
    )
    service._trust = SimpleNamespace(
        calculate_trust_score=AsyncMock(
            return_value=SimpleNamespace(
                model_dump=lambda: {
                    "overall": 50,
                    "status": "incomplete_verification",
                    "score_version": "v1",
                    "domain_details": {"employment": "Hidden Employer"},
                    "positive_contributors": ["Hidden Institution"],
                    "manual_review_reason": "Private detail",
                }
            )
        )
    )
    return service, records, link


@pytest.mark.asyncio
async def test_verified_queries_filter_before_projection_and_documents_do_not_qualify():
    service, records, _ = public_service(snapshot())
    result = await service.get_by_token("synthetic-test-credential")
    assert [row.verification_status for row in result.vault.employments] == ["verified"]
    assert [row.verification_status for row in result.vault.educations] == ["verified"]
    assert result.vault.certifications == result.vault.projects == []
    assert result.trust_score is None
    assert result.profile.model_dump() == dict(
        full_name="QA Owner", headline=None, location=None, avatar_url=None, profile_slug=None
    )
    assert result.vault.employments[0].documents == []
    assert len(records.queries) == 2
    service._trust.calculate_trust_score.assert_not_called()
    assert result.share.policy_version == 2 and result.share.sharing_mode == "verified_only"


@pytest.mark.asyncio
async def test_mixed_selected_records_are_truthful_and_hidden_sections_never_queried():
    service, records, _ = public_service(
        snapshot(
            "verified_and_candidate_provided", include_certifications=True, include_projects=True
        )
    )
    result = await service.get_by_token("synthetic-test-credential")
    assert result.vault.employments == result.vault.educations == []
    assert result.vault.certifications[0].verification_status == "self_declared"
    assert result.vault.projects[0].verification_status == "self_declared"
    assert result.vault.certifications[0].credential_url is None
    assert len(records.queries) == 2


@pytest.mark.asyncio
async def test_pending_and_legacy_approved_never_gain_verified_status_in_v2():
    service, _, _ = public_service(
        snapshot(
            "verified_and_candidate_provided", include_employments=True, include_educations=True
        )
    )
    result = await service.get_by_token("synthetic-test-credential")
    assert [row.verification_status for row in result.vault.employments] == [
        "verified",
        "self_declared",
        "draft",
        "submitted",
        "under_review",
    ]
    assert [row.verification_status for row in result.vault.educations] == [
        "verified",
        "pending",
        "draft",
    ]


@pytest.mark.asyncio
async def test_derived_score_allowlist_cannot_leak_hidden_contributors():
    service, _, _ = public_service(
        snapshot(show_trust_score=True, include_employments=False, include_educations=False)
    )
    result = await service.get_by_token("synthetic-test-credential")
    serialized = result.model_dump_json()
    assert result.trust_score.overall == 50
    assert set(result.trust_score.model_dump()) == set(PublicPassportTrustScore.model_fields)
    for private in [
        "Hidden Employer",
        "Hidden Institution",
        "Private detail",
        "domain_details",
        "contributors",
        "manual_review_reason",
        "breakdown",
    ]:
        assert private not in serialized
    service._trust.calculate_trust_score.assert_awaited_once()


@pytest.mark.parametrize("photo", [True, False])
@pytest.mark.asyncio
async def test_profile_photo_opt_in_never_returns_storage_url(photo):
    service, _, _ = public_service(
        snapshot("verified_and_candidate_provided", include_profile=True, show_photo=photo)
    )
    result = await service.get_by_token("synthetic-test-credential")
    assert result.profile.headline == "Private headline"
    assert bool(result.profile.avatar_url) is photo
    assert "amazonaws" not in result.model_dump_json()
    assert "email" not in result.profile.model_dump() and "phone" not in result.profile.model_dump()


@pytest.mark.parametrize("state", ["missing", "expired", "revoked", "malformed"])
@pytest.mark.asyncio
async def test_token_terminal_states_fail_closed_before_any_profile_or_record_load(state):
    service, records, link = public_service(snapshot())
    if state == "missing":
        service._shares.get_by_token_hash.return_value = None
    elif state == "expired":
        link.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    elif state == "revoked":
        link.revoked_at = datetime.now(UTC)
    else:
        link.permissions = {"verified_only": False}
    with pytest.raises(NotFoundError):
        await service.get_by_token("synthetic-test-credential")
    with pytest.raises(NotFoundError):
        await service.get_photo_by_token("synthetic-test-credential")
    service._users.get_public_profile.assert_not_called()
    assert records.queries == []


@pytest.mark.asyncio
async def test_photo_gate_precedes_storage_access():
    service, records, _ = public_service(snapshot())
    with pytest.raises(NotFoundError):
        await service.get_photo_by_token("synthetic-test-credential")
    assert records.queries == []


@pytest.mark.parametrize(
    "url",
    [
        "s3://bucket/key",
        "https://bucket.s3.amazonaws.com/key",
        "https://example.com/photo?X-Amz-Signature=synthetic",
        "javascript:alert(1)",
        "http://example.com",
        "https://user:pass@example.com",
    ],
)
def test_recipient_storage_url_guard(url):
    assert safe_recipient_url(url) is None
    assert safe_recipient_url("https://example.com/project") == "https://example.com/project"


@pytest.mark.asyncio
async def test_owned_update_locks_row_and_rejects_v2_null_without_mutation():
    now = datetime.now(UTC)
    link = SimpleNamespace(
        id=uuid4(),
        label="Original",
        permissions=snapshot(),
        revoked_at=None,
        expires_at=None,
        track_views=True,
        last_viewed_at=None,
        created_at=now,
        updated_at=now,
    )
    session = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    service = PassportShareService(session, SimpleNamespace())
    service._repo = SimpleNamespace(get_owned=AsyncMock(return_value=link))
    owner = uuid4()
    with pytest.raises(ValidationAppError):
        await service.update(owner, link.id, PassportShareUpdateRequest(label=None))
    service._repo.get_owned.assert_awaited_once_with(link.id, owner, for_update=True)
    session.commit.assert_not_called()
    assert link.label == "Original"
    result = await service.update(
        owner, link.id, PassportShareUpdateRequest(permissions={"include_educations": False})
    )
    assert result.label == "Original" and result.permissions.include_employments
    assert not result.permissions.include_educations
    assert result.policy_version == 2


@pytest.mark.asyncio
async def test_repository_lock_has_owner_scope_and_refreshes_stale_identity_map():
    session = SimpleNamespace(execute=AsyncMock(return_value=Result([])))
    owner, share = uuid4(), uuid4()
    await PassportShareRepository(session).get_owned(share, owner, for_update=True)
    query = session.execute.call_args.args[0]
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql and "owner_user_id" in sql and "passport_share_links.id" in sql
    assert query.get_execution_options()["populate_existing"] is True


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"label": None},
        {"label": " "},
        {"label": "a" * 121},
        {"label": "QA", "permissions": {"show_photo": True}},
    ],
)
@pytest.mark.asyncio
async def test_create_route_returns_422_before_service(payload):
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=uuid4(), email="qa@example.com", role="user"
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/passport-shares", json=payload)
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_capabilities_auth_and_openapi_contract():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/passport-shares/capabilities")
        assert response.status_code == 401
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=uuid4(), email="qa@example.com", role="user"
        )
        try:
            response = await client.get("/api/v1/passport-shares/capabilities")
            assert response.status_code == 200
            assert response.json()["default_mode"] == "verified_only"
            assert response.json()["verified_only_sections"] == [
                "include_employments",
                "include_educations",
            ]
        finally:
            app.dependency_overrides.clear()
    schema = app.openapi()["components"]["schemas"]
    assert "label" in schema["PassportShareCreateRequest"]["required"]
    assert "policy_version" in schema["PassportShareResponse"]["properties"]
    assert "domain_details" not in schema["PublicPassportTrustScore"]["properties"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content_type,content,allowed",
    [
        ("image/png", b"synthetic-image", True),
        ("text/html", b"<script>", False),
        ("image/png", b"", False),
        ("image/png", b"x" * (5 * 1024 * 1024 + 1), False),
    ],
)
async def test_photo_proxy_bounds_content_and_never_redirects_to_storage(
    monkeypatch, content_type, content, allowed
):
    service, _, _ = public_service(
        snapshot("verified_and_candidate_provided", include_profile=True, show_photo=True)
    )
    service._session = SimpleNamespace(
        execute=AsyncMock(return_value=Result([SimpleNamespace(avatar_key="qa/photo")]))
    )
    service._settings = SimpleNamespace(s3_documents_bucket="synthetic-bucket")
    body = MagicMock()
    body.read.return_value = content
    storage = MagicMock()
    storage.get_object.return_value = {"Body": body, "ContentType": content_type}
    monkeypatch.setattr("app.infrastructure.s3.client.get_s3_client", lambda _: storage)
    if allowed:
        assert await service.get_photo_by_token("synthetic") == (content, content_type)
    else:
        with pytest.raises(NotFoundError):
            await service.get_photo_by_token("synthetic")
    body.close.assert_called_once()


def test_existing_null_purpose_and_legacy_permissions_are_read_without_rewrite():
    now = datetime.now(UTC)
    values = {"include_employments": False, "include_projects": True}
    link = SimpleNamespace(
        id=uuid4(),
        label=None,
        permissions=values.copy(),
        revoked_at=None,
        expires_at=None,
        track_views=True,
        last_viewed_at=None,
        created_at=now,
        updated_at=now,
    )
    result = PassportShareService(SimpleNamespace(), SimpleNamespace())._to_response(link)
    assert result.label is None
    assert (result.policy_version, result.sharing_mode) == (1, "legacy_mixed")
    assert link.permissions == values
    assert not result.permissions.include_employments and result.permissions.include_projects
