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
from app.main import app
from app.schemas.admin_organization import (
    AdminOrganizationActivityItem,
    AdminOrganizationActivityPage,
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
from app.services.admin_organization_service import (
    AdminOrganizationService,
    build_overview_counts,
)

ORG_ID = UUID("10000000-0000-0000-0000-000000000001")
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
                    subject_public_id=REQUEST_ID,
                    new_status="pending_admin_review",
                )
            ],
            total=1,
            params=params,
        )


@pytest.mark.asyncio
async def test_company_360_routes_return_backend_truth() -> None:
    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[get_admin_organization_service] = (
        lambda: FakeAdminOrganizationService()
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

    app.dependency_overrides.clear()
    assert directory.status_code == 200
    assert directory.json()["items"][0]["name"] == "XYZ Pharma"
    assert directory.json()["items"][0]["people_count"] == 126
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


@pytest.mark.asyncio
async def test_company_360_rejects_unauthenticated_and_non_admin_users() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        unauthenticated = await client.get("/api/v1/admin/organizations")

    app.dependency_overrides[get_current_user] = _candidate_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        candidate = await client.get("/api/v1/admin/organizations")
        candidate_detail = await client.get(f"/api/v1/admin/organizations/{ORG_ID}")
    app.dependency_overrides.clear()

    assert unauthenticated.status_code == 401
    assert candidate.status_code == 403
    assert candidate_detail.status_code == 403


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


def test_page_contract_keeps_pagination_stable() -> None:
    params = PageParams(page=2, page_size=10)
    page = AdminOrganizationPeoplePage.create(items=[], total=21, params=params)
    assert page.page == 2
    assert page.page_size == 10
    assert page.total_pages == 3


@pytest.mark.asyncio
async def test_company_sections_are_scoped_to_the_requested_organization() -> None:
    class EmptyRows:
        def all(self):
            return []

        def __iter__(self):
            return iter(())

    async def capture_query(method_name: str, params: object):
        organization = SimpleNamespace(id=ORG_ID)
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
