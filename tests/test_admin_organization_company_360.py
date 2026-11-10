"""Contracts for Admin organization search and Company 360."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql

from app.api.dependencies.services import get_admin_organization_service
from app.auth.deps import CurrentUser, get_current_user
from app.exceptions import ConflictError, NotFoundError
from app.main import app
from app.models.organization_activity_event import OrganizationActivityEvent
from app.models.trust_registry_domain import TrustRegistryDomain
from app.models.trust_registry_record import TrustRegistryRecord
from app.schemas.admin_organization import (
    AdminOrganizationActivityItem,
    AdminOrganizationActivityPage,
    AdminOrganizationCompanyRecordConnectRequest,
    AdminOrganizationCompanyRecordCreateRequest,
    AdminOrganizationCompanyRecordResponse,
    AdminOrganizationDetailResponse,
    AdminOrganizationListItem,
    AdminOrganizationPage,
    AdminOrganizationPeoplePage,
    AdminOrganizationPersonItem,
    AdminOrganizationTeamItem,
    AdminOrganizationTeamPage,
    AdminOrganizationVerificationItem,
    AdminOrganizationVerificationListParams,
    AdminOrganizationVerificationPage,
)
from app.schemas.pagination import ListQueryParams, PageParams
from app.services.admin_directory_service import candidate_identity_filter
from app.services.admin_organization_service import (
    AdminOrganizationService,
    build_overview_counts,
)

ORG_ID = UUID("10000000-0000-0000-0000-000000000001")
REGISTRY_ID = UUID("10000000-0000-0000-0000-000000000002")
PERSON_ID = UUID("20000000-0000-0000-0000-000000000001")
REQUEST_ID = UUID("30000000-0000-0000-0000-000000000001")
MEMBER_ID = UUID("40000000-0000-0000-0000-000000000001")
EVENT_ID = UUID("50000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 10, 4, 8, 0, tzinfo=UTC)


async def _admin_user() -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        email="admin@example.test",
        role="admin",
        full_name="Admin Operator",
    )


async def _candidate_user() -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        email="candidate@example.test",
        role="user",
        full_name="Candidate",
    )


class FakeAdminOrganizationService:
    async def list_organizations(self, params):  # noqa: ANN001
        assert params.search == "XYZ"
        return AdminOrganizationPage.create(
            items=[
                AdminOrganizationListItem(
                    public_id=ORG_ID,
                    name="XYZ Pharma",
                    domain="xyzpharma.test",
                    organization_type="employer",
                    registry_record_public_id=REGISTRY_ID,
                    account_status="active",
                    verification_state="verified",
                    is_workspace_customer=True,
                    people_count=126,
                    request_count=284,
                    verified_count=241,
                    pending_count=31,
                    in_progress_count=8,
                    needs_attention_count=4,
                    team_size=6,
                    updated_at=NOW,
                )
            ],
            total=1,
            params=params,
        )

    async def get_organization(self, public_id):  # noqa: ANN001
        assert public_id == ORG_ID
        return AdminOrganizationDetailResponse(
            public_id=ORG_ID,
            name="XYZ Pharma",
            domain="xyzpharma.test",
            organization_type="employer",
            account_status="active",
            verification_state="verified",
            onboarding_status="completed",
            is_workspace_customer=True,
            primary_owner_name="Workspace Owner",
            primary_owner_email_masked="ow***@xyzpharma.test",
            team_size=6,
            people_count=126,
            created_at=NOW,
            updated_at=NOW,
            last_activity_at=NOW,
        )

    async def get_overview(self, public_id):  # noqa: ANN001
        assert public_id == ORG_ID
        return build_overview_counts(
            people_count=126,
            status_counts={"verified": 241, "pending_admin_review": 31, "in_progress": 8},
            type_counts={"employment": 180, "education": 100},
        )

    async def list_people(self, public_id, params):  # noqa: ANN001
        assert public_id == ORG_ID
        return AdminOrganizationPeoplePage.create(
            items=[
                AdminOrganizationPersonItem(
                    public_id=PERSON_ID,
                    display_name="Candidate One",
                    email_masked="ca*******@example.test",
                    relationship="candidate",
                    lifecycle_status="active",
                    invitation_status="not_invited",
                    verification_request_count=3,
                    verified_count=2,
                    pending_count=1,
                    last_activity_at=NOW,
                )
            ],
            total=1,
            params=params,
        )

    async def list_verifications(self, public_id, params):  # noqa: ANN001
        assert public_id == ORG_ID
        assert params.verification_type == "employment"
        return AdminOrganizationVerificationPage.create(
            items=[
                AdminOrganizationVerificationItem(
                    public_id=REQUEST_ID,
                    organization_person_public_id=PERSON_ID,
                    candidate_name="Candidate One",
                    candidate_email_masked="ca*******@example.test",
                    request_type="employment",
                    requested_by="Workspace Owner",
                    created_at=NOW,
                    status="verified",
                    completed_at=NOW,
                    updated_at=NOW,
                )
            ],
            total=1,
            params=params,
        )

    async def list_team(self, public_id, params):  # noqa: ANN001
        assert public_id == ORG_ID
        return AdminOrganizationTeamPage.create(
            items=[
                AdminOrganizationTeamItem(
                    public_id=MEMBER_ID,
                    user_public_id=uuid4(),
                    display_name="Workspace Owner",
                    email_masked="ow***@xyzpharma.test",
                    role="owner",
                    status="active",
                    joined_at=NOW,
                    last_activity_at=NOW,
                )
            ],
            total=1,
            params=params,
        )

    async def list_activity(self, public_id, params):  # noqa: ANN001
        assert public_id == ORG_ID
        return AdminOrganizationActivityPage.create(
            items=[
                AdminOrganizationActivityItem(
                    public_id=EVENT_ID,
                    occurred_at=NOW,
                    event_type="verification_submitted",
                    source="verification_request",
                    organization_name="XYZ Pharma",
                    subject_public_id=str(REQUEST_ID),
                    new_status="pending_admin_review",
                )
            ],
            total=1,
            params=params,
        )

    async def connect_company_record(self, actor_id, public_id, payload):  # noqa: ANN001
        assert public_id == ORG_ID
        assert payload.registry_record_public_id == REGISTRY_ID
        return AdminOrganizationCompanyRecordResponse(
            organization_public_id=ORG_ID,
            registry_record_public_id=REGISTRY_ID,
            registry_record_name="XYZ Pharma Record",
            registry_record_organization_type="employer",
            registry_record_primary_domain="xyzpharma.test",
            lifecycle_status="draft",
            trust_status="unreviewed",
            created=False,
            already_connected=False,
        )

    async def create_and_connect_company_record(
        self,
        actor_id,
        public_id,
        payload,  # noqa: ANN001
    ):
        assert public_id == ORG_ID
        assert payload.legal_name == "XYZ Pharma Private Limited"
        return AdminOrganizationCompanyRecordResponse(
            organization_public_id=ORG_ID,
            registry_record_public_id=REGISTRY_ID,
            registry_record_name="XYZ Pharma",
            registry_record_organization_type="employer",
            registry_record_primary_domain="xyzpharma.test",
            lifecycle_status="draft",
            trust_status="unreviewed",
            created=True,
            already_connected=False,
        )


@pytest.mark.asyncio
async def test_company_360_routes_return_backend_truth() -> None:
    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[get_admin_organization_service] = lambda: (
        FakeAdminOrganizationService()
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        directory = await client.get(
            "/api/v1/admin/organizations",
            params={"search": "XYZ", "page": 1, "page_size": 20},
        )
        detail = await client.get(f"/api/v1/admin/organizations/{ORG_ID}")
        overview = await client.get(f"/api/v1/admin/organizations/{ORG_ID}/overview")
        people = await client.get(f"/api/v1/admin/organizations/{ORG_ID}/people")
        verifications = await client.get(
            f"/api/v1/admin/organizations/{ORG_ID}/verifications",
            params={"verification_type": "employment"},
        )
        team = await client.get(f"/api/v1/admin/organizations/{ORG_ID}/team")
        activity = await client.get(f"/api/v1/admin/organizations/{ORG_ID}/activity")
        connected = await client.post(
            f"/api/v1/admin/organizations/{ORG_ID}/company-record/connect",
            json={
                "registry_record_public_id": str(REGISTRY_ID),
                "idempotency_key": str(uuid4()),
            },
        )
        created = await client.post(
            f"/api/v1/admin/organizations/{ORG_ID}/company-record/create-and-connect",
            json={
                "idempotency_key": str(uuid4()),
                "legal_name": "XYZ Pharma Private Limited",
                "display_name": "XYZ Pharma",
                "organization_type": "employer",
                "country": "IN",
                "primary_domain": "xyzpharma.test",
            },
        )

    app.dependency_overrides.clear()
    assert directory.status_code == 200
    assert directory.json()["items"][0]["name"] == "XYZ Pharma"
    assert directory.json()["items"][0]["people_count"] == 126
    assert directory.json()["items"][0]["registry_record_public_id"] == str(REGISTRY_ID)
    assert detail.status_code == 200
    assert detail.json()["primary_owner_email_masked"] == "ow***@xyzpharma.test"
    assert overview.status_code == 200
    assert overview.json()["verified_count"] == 241
    assert overview.json()["type_counts"]["employment"] == 180
    assert people.status_code == 200
    assert people.json()["items"][0]["public_id"] == str(PERSON_ID)
    assert verifications.status_code == 200
    assert verifications.json()["items"][0]["public_id"] == str(REQUEST_ID)
    assert team.status_code == 200
    assert team.json()["items"][0]["role"] == "owner"
    assert activity.status_code == 200
    assert activity.json()["items"][0]["source"] == "verification_request"
    assert connected.status_code == 200
    assert connected.json()["registry_record_name"] == "XYZ Pharma Record"
    assert created.status_code == 201
    assert created.json()["lifecycle_status"] == "draft"
    assert created.json()["trust_status"] == "unreviewed"


@pytest.mark.asyncio
async def test_company_360_rejects_unauthenticated_and_non_admin_users() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        unauthenticated = await client.get("/api/v1/admin/organizations")

    app.dependency_overrides[get_current_user] = _candidate_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        candidate = await client.get("/api/v1/admin/organizations")
        candidate_detail = await client.get(f"/api/v1/admin/organizations/{ORG_ID}")
        candidate_invitations = await client.get(
            f"/api/v1/admin/organizations/{ORG_ID}/team-invitations"
        )
        candidate_roles = await client.get(f"/api/v1/admin/organizations/{ORG_ID}/job-roles")
        candidate_imports = await client.get(f"/api/v1/admin/organizations/{ORG_ID}/people-imports")
        candidate_create_role = await client.post(
            f"/api/v1/admin/organizations/{ORG_ID}/job-roles",
            json={"name": "Unauthorized role", "mode": "submit"},
        )
        candidate_connect = await client.post(
            f"/api/v1/admin/organizations/{ORG_ID}/company-record/connect",
            json={
                "registry_record_public_id": str(REGISTRY_ID),
                "idempotency_key": str(uuid4()),
            },
        )
        candidate_create_record = await client.post(
            f"/api/v1/admin/organizations/{ORG_ID}/company-record/create-and-connect",
            json={
                "idempotency_key": str(uuid4()),
                "legal_name": "Forbidden",
                "organization_type": "employer",
                "country": "IN",
            },
        )
    app.dependency_overrides.clear()

    assert unauthenticated.status_code == 401
    assert candidate.status_code == 403
    assert candidate_detail.status_code == 403
    assert candidate_invitations.status_code == 403
    assert candidate_roles.status_code == 403
    assert candidate_imports.status_code == 403
    assert candidate_create_role.status_code == 403
    assert candidate_connect.status_code == 403
    assert candidate_create_record.status_code == 403


def test_overview_uses_canonical_status_taxonomy_and_defensible_rate() -> None:
    overview = build_overview_counts(
        people_count=5,
        status_counts={
            "draft": 1,
            "pending_admin_review": 2,
            "pending_organization_acceptance": 3,
            "verified": 4,
            "rejected": 1,
            "unable_to_verify": 1,
            "cancelled": 1,
            "withdrawn_by_candidate": 1,
        },
        type_counts={"employment": 8, "education": 6},
    )

    assert overview.verification_total == 14
    assert overview.pending_count == 3
    assert overview.in_progress_count == 3
    assert overview.needs_attention_count == 2
    assert overview.completion_rate_numerator == 4
    assert overview.completion_rate_denominator == 11
    assert overview.completion_rate == 36.4


def test_company_search_is_partial_case_insensitive_and_supports_domain_id_owner() -> None:
    expression = AdminOrganizationService._search_filter("xYz")
    sql = str(
        expression.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()

    assert "%xyz%" in sql
    assert "organizations.name ilike" in sql
    assert "organizations.domain" in sql
    assert "organizations.public_id" in sql
    assert "users.email ilike" in sql
    assert "organization_members" in sql


def test_candidate_directory_uses_identity_provenance_not_the_shared_auth_role() -> None:
    sql = str(
        candidate_identity_filter().compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()

    assert "users.role = 'user'" in sql
    assert "pending_signups" in sql
    assert "pending_signups.signup_kind = 'candidate'" in sql
    assert "pending_signups.signup_kind = 'organization'" in sql
    assert "organization_members" in sql
    assert "organization_people" in sql
    assert "organization_people.relationship = 'candidate'" in sql


@pytest.mark.asyncio
async def test_company_activity_query_includes_persisted_organization_events() -> None:
    class EmptyRows:
        def __iter__(self):
            return iter(())

    organization = SimpleNamespace(id=ORG_ID, name="XYZ Pharma")
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[organization, 0]),
        execute=AsyncMock(return_value=EmptyRows()),
    )
    service = AdminOrganizationService(session)  # type: ignore[arg-type]
    await service.list_activity(ORG_ID, ListQueryParams(page=1, page_size=20))
    statement = session.execute.await_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    assert "organization_activity_events" in sql
    assert "organization_activity" in sql
    assert str(ORG_ID) in sql


@pytest.mark.asyncio
async def test_company_directory_uses_aggregates_without_per_row_queries() -> None:
    empty_result = SimpleNamespace(all=lambda: [])
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=0),
        execute=AsyncMock(return_value=empty_result),
    )
    service = AdminOrganizationService(session)  # type: ignore[arg-type]

    page = await service.list_organizations(
        SimpleNamespace(
            search=None,
            organization_type=None,
            status=None,
            offset=0,
            limit=20,
            page=1,
            page_size=20,
        )
    )

    assert page.items == []
    assert page.total == 0
    assert session.scalar.await_count == 1
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_company_directory_projects_canonical_identity_without_per_row_lookup() -> None:
    organization = SimpleNamespace(
        public_id=ORG_ID,
        name="XYZ Pharma",
        domain="xyzpharma.test",
        organization_type="employer",
        suspended_at=None,
        setup_completed_at=NOW,
        verification_state="verified",
        updated_at=NOW,
    )
    rows = SimpleNamespace(
        all=lambda: [
            (
                organization,
                REGISTRY_ID,
                "XYZ Pharma Record",
                126,
                6,
                284,
                241,
                31,
                8,
                4,
            )
        ]
    )
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=1),
        execute=AsyncMock(return_value=rows),
    )
    service = AdminOrganizationService(session)  # type: ignore[arg-type]

    page = await service.list_organizations(
        SimpleNamespace(
            search=None,
            organization_type=None,
            status=None,
            offset=0,
            limit=20,
            page=1,
            page_size=20,
        )
    )

    assert page.items[0].registry_record_public_id == REGISTRY_ID
    assert page.items[0].registry_record_name == "XYZ Pharma Record"
    assert session.execute.await_count == 1


def test_page_contract_keeps_pagination_stable() -> None:
    params = PageParams(page=2, page_size=10)
    page = AdminOrganizationPeoplePage.create(items=[], total=21, params=params)
    assert page.page == 2
    assert page.page_size == 10
    assert page.total_pages == 3


def test_company_list_contract_exposes_canonical_identity_link() -> None:
    item = AdminOrganizationListItem(
        public_id=ORG_ID,
        name="XYZ Pharma",
        organization_type="employer",
        registry_record_public_id=REGISTRY_ID,
        account_status="active",
        verification_state="verified",
        is_workspace_customer=True,
        updated_at=NOW,
    )

    assert item.registry_record_public_id == REGISTRY_ID


class MutationSession:
    def __init__(self, *scalar_values: object) -> None:
        self.scalar_values = list(scalar_values)
        self.scalar_statements: list[object] = []
        self.added: list[object] = []
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def scalar(self, statement):  # noqa: ANN001
        self.scalar_statements.append(statement)
        return self.scalar_values.pop(0)

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        for value in self.added:
            if hasattr(value, "id") and getattr(value, "id", None) is None:
                value.id = uuid4()


def _organization(*, registry_record_id: UUID | None = None, metadata=None):  # noqa: ANN001
    return SimpleNamespace(
        id=ORG_ID,
        public_id=ORG_ID,
        registry_record_id=registry_record_id,
        registry_resolution_metadata=metadata or {},
        registry_resolution_method=None,
        registry_resolution_confidence=None,
        registry_resolved_at=None,
        registry_resolved_by_user_id=None,
    )


def _registry_record():
    return SimpleNamespace(
        id=REGISTRY_ID,
        public_id=REGISTRY_ID,
        legal_name="XYZ Pharma Private Limited",
        display_name="XYZ Pharma",
        organization_type="employer",
        lifecycle_status="draft",
        trust_status="unreviewed",
    )


@pytest.mark.asyncio
async def test_connect_company_record_is_idempotent_and_actor_attributed() -> None:
    actor_id = uuid4()
    organization = _organization()
    record = _registry_record()
    session = MutationSession(organization, record, "xyzpharma.test")
    service = AdminOrganizationService(session)  # type: ignore[arg-type]
    payload = AdminOrganizationCompanyRecordConnectRequest(
        registry_record_public_id=REGISTRY_ID,
        idempotency_key=uuid4(),
    )

    result = await service.connect_company_record(actor_id, ORG_ID, payload)

    assert result.registry_record_name == "XYZ Pharma"
    assert result.created is False
    assert organization.registry_record_id == REGISTRY_ID
    assert organization.registry_resolved_by_user_id == actor_id
    event = next(item for item in session.added if isinstance(item, OrganizationActivityEvent))
    assert event.actor_user_id == actor_id
    assert event.event_type == "company_record_connected"
    session.commit.assert_awaited_once()

    retry_session = MutationSession(organization, record, "xyzpharma.test")
    retry = await AdminOrganizationService(retry_session).connect_company_record(  # type: ignore[arg-type]
        actor_id,
        ORG_ID,
        payload,
    )
    assert retry.already_connected is True
    assert retry_session.added == []
    retry_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_company_record_is_draft_unverified_atomic_and_retry_safe() -> None:
    actor_id = uuid4()
    request_key = uuid4()
    organization = _organization()
    session = MutationSession(organization)
    service = AdminOrganizationService(session)  # type: ignore[arg-type]
    payload = AdminOrganizationCompanyRecordCreateRequest(
        idempotency_key=request_key,
        legal_name="XYZ Pharma Private Limited",
        display_name="XYZ Pharma",
        organization_type="employer",
        country="in",
        state_province="Karnataka",
        website="https://xyzpharma.test",
        primary_domain="XYZPHARMA.TEST",
    )

    result = await service.create_and_connect_company_record(actor_id, ORG_ID, payload)

    record = next(item for item in session.added if isinstance(item, TrustRegistryRecord))
    domain = next(item for item in session.added if isinstance(item, TrustRegistryDomain))
    event = next(item for item in session.added if isinstance(item, OrganizationActivityEvent))
    assert result.created is True
    assert result.lifecycle_status == "draft"
    assert result.trust_status == "unreviewed"
    assert record.lifecycle_status == "draft"
    assert record.trust_status == "unreviewed"
    assert record.registry_confidence_score == 0
    assert domain.domain == "xyzpharma.test"
    assert domain.is_verified is False
    assert organization.registry_record_id == record.id
    assert event.actor_user_id == actor_id
    assert event.event_type == "company_record_created_and_connected"
    session.commit.assert_awaited_once()

    organization.registry_resolution_metadata = {"idempotency_key": str(request_key)}
    retry_session = MutationSession(organization, record, "xyzpharma.test")
    retry = await AdminOrganizationService(  # type: ignore[arg-type]
        retry_session
    ).create_and_connect_company_record(actor_id, ORG_ID, payload)
    assert retry.already_connected is True
    assert retry.registry_record_public_id == record.public_id
    assert retry_session.added == []
    retry_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_company_record_connection_rejects_a_different_existing_target() -> None:
    organization = _organization(registry_record_id=uuid4())
    session = MutationSession(organization, _registry_record())
    service = AdminOrganizationService(session)  # type: ignore[arg-type]

    with pytest.raises(ConflictError, match="already connected"):
        await service.connect_company_record(
            uuid4(),
            ORG_ID,
            AdminOrganizationCompanyRecordConnectRequest(
                registry_record_public_id=REGISTRY_ID,
                idempotency_key=uuid4(),
            ),
        )

    session.commit.assert_not_awaited()
    assert session.added == []


@pytest.mark.asyncio
async def test_company_record_connection_rejects_an_invalid_target_without_mutation() -> None:
    session = MutationSession(_organization(), None)
    service = AdminOrganizationService(session)  # type: ignore[arg-type]

    with pytest.raises(NotFoundError, match="Company record not found"):
        await service.connect_company_record(
            uuid4(),
            ORG_ID,
            AdminOrganizationCompanyRecordConnectRequest(
                registry_record_public_id=uuid4(),
                idempotency_key=uuid4(),
            ),
        )

    session.commit.assert_not_awaited()
    assert session.added == []


@pytest.mark.asyncio
async def test_company_record_mutations_lock_the_client_row_for_concurrent_submissions() -> None:
    session = MutationSession(_organization())
    service = AdminOrganizationService(session)  # type: ignore[arg-type]

    await service._require_organization_for_update(ORG_ID)

    sql = str(
        session.scalar_statements[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    assert "for update" in sql


@pytest.mark.asyncio
async def test_company_sections_are_scoped_to_the_requested_organization() -> None:
    class EmptyRows:
        def all(self):
            return []

        def __iter__(self):
            return iter(())

    async def capture_query(method_name: str, params: object):
        organization = SimpleNamespace(id=ORG_ID, name="XYZ Pharma")
        session = SimpleNamespace(
            scalar=AsyncMock(side_effect=[organization, 0]),
            execute=AsyncMock(return_value=EmptyRows()),
        )
        service = AdminOrganizationService(session)  # type: ignore[arg-type]
        await getattr(service, method_name)(ORG_ID, params)
        return session.execute.await_args.args[0]

    list_params = ListQueryParams(page=1, page_size=20)
    verification_params = AdminOrganizationVerificationListParams(page=1, page_size=20)
    queries = {
        "people": await capture_query("list_people", list_params),
        "verifications": await capture_query("list_verifications", verification_params),
        "team": await capture_query("list_team", list_params),
        "activity": await capture_query("list_activity", list_params),
    }

    for section, query in queries.items():
        sql = str(
            query.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).lower()
        assert str(ORG_ID) in sql, f"{section} query lost organization scoping"
