"""Route contracts for additive Admin review read APIs."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import (
    get_admin_directory_service,
    get_employer_verification_service,
    get_verification_request_admin_review_service,
)
from app.main import app
from app.organization.enums import OrganizationType
from app.repositories.employer_verification import EmployerVerificationRepository
from app.schemas.admin_directory import (
    AdminOrganizationSearchItem,
    AdminOrganizationSearchPage,
    AdminReviewerPage,
    AdminReviewerResponse,
    AdminUserCareerSummary,
    AdminUserDetailResponse,
    AdminUserDirectoryItem,
    AdminUserPage,
    AdminUserPassportSummary,
    AdminUserTrustSummary,
    AdminUserVerificationBreakdown,
    AdminUserVerificationItem,
    AdminUserVerificationSummary,
)
from app.schemas.admin_review_workflow import AdminEvidenceDownloadResponse
from app.schemas.employer_verification import (
    AdminEmployerVerificationResponse,
    AdminEmployerVerificationSummary,
)
from app.services.admin_directory_service import normalize_organization_type


async def _admin_user() -> CurrentUser:
    return CurrentUser(
        id=UUID("00000000-0000-0000-0000-000000000999"),
        email="admin@kairo.test",
        role="admin",
    )


async def _candidate_user() -> CurrentUser:
    return CurrentUser(id=uuid4(), email="candidate@kairo.test", role="user")


async def _hr_user() -> CurrentUser:
    return CurrentUser(id=uuid4(), email="hr@kairo.test", role="hr")


async def _support_user() -> CurrentUser:
    return CurrentUser(id=uuid4(), email="support@kairo.test", role="support")


@pytest.mark.parametrize(
    ("organization_type", "expected"),
    [(OrganizationType.EMPLOYER, "employer"), ("university", "university")],
)
def test_admin_organization_type_normalization(organization_type, expected) -> None:  # noqa: ANN001
    assert normalize_organization_type(organization_type) == expected


class FakeAdminDirectoryService:
    async def list_reviewers(self, params):  # noqa: ANN001
        return AdminReviewerPage.create(
            items=[
                AdminReviewerResponse(
                    user_id=uuid4(),
                    full_name="Reviewer",
                    email="reviewer@kairo.test",
                    role="hr",
                )
            ],
            total=1,
            params=params,
        )

    async def search_organizations(self, params):  # noqa: ANN001
        return AdminOrganizationSearchPage.create(
            items=[
                AdminOrganizationSearchItem(
                    public_id=uuid4(),
                    name="Acme Corp",
                    organization_type="employer",
                    verification_capabilities=["employment"],
                    registry_record_public_id=None,
                    registry_resolution_status="unresolved",
                )
            ],
            total=1,
            params=params,
        )

    async def list_users(self, params):  # noqa: ANN001
        return AdminUserPage.create(
            items=[
                AdminUserDirectoryItem(
                    public_id=uuid4(),
                    display_name="Candidate One",
                    masked_email="ca***********@example.com",
                    account_status="active",
                    created_at=datetime.now(tz=UTC),
                    profile_completion_percentage=78,
                    trust_score_overall=82,
                    trust_score_status="ready",
                    active_verification_count=1,
                    completed_verification_count=2,
                    career_record_count=4,
                    active_passport_share_count=1,
                )
            ],
            total=1,
            params=params,
        )

    async def get_user_detail(self, user_public_id):  # noqa: ANN001
        now = datetime.now(tz=UTC)
        if str(user_public_id).endswith("2222"):
            return AdminUserDetailResponse(
                public_id=user_public_id,
                display_name="Deleted Candidate",
                account_status="deleted",
                email="Redacted",
                masked_email="Redacted",
                phone=None,
                masked_phone=None,
                created_at=now,
                updated_at=now,
                deleted_at=now,
                trust=AdminUserTrustSummary(),
                career_summary=AdminUserCareerSummary(),
                verification_summary=AdminUserVerificationSummary(
                    overall=AdminUserVerificationBreakdown(total=1, statuses={"verified": 1}),
                    employments=AdminUserVerificationBreakdown(total=1, statuses={"verified": 1}),
                    educations=AdminUserVerificationBreakdown(),
                    certifications=AdminUserVerificationBreakdown(),
                ),
                verifications=[
                    AdminUserVerificationItem(
                        public_id=uuid4(),
                        request_type="employment",
                        status="verified",
                        organization_name="Acme Corp",
                        linked_record_label="Employment record",
                        created_at=now,
                        updated_at=now,
                    )
                ],
                passport=AdminUserPassportSummary(ready=False),
                activity=[],
            )
        return AdminUserDetailResponse(
            public_id=user_public_id,
            display_name="Candidate One",
            account_status="active",
            email="candidate.one@example.com",
            masked_email="ca***********@example.com",
            phone="+15551234567",
            masked_phone="+15 •••••••67",
            headline="Operations Lead",
            current_role="Operations Lead",
            location="Bengaluru, IN",
            created_at=now,
            updated_at=now,
            email_verified=True,
            phone_verified=True,
            onboarding_completed=True,
            profile_completion_percentage=78,
            trust=AdminUserTrustSummary(
                overall=82,
                status="ready",
                verification_completeness_percentage=75,
                last_calculated_at=now,
            ),
            career_summary=AdminUserCareerSummary(
                total_items=4,
                employments=1,
                educations=1,
                certifications=1,
                projects=1,
            ),
            verification_summary=AdminUserVerificationSummary(
                overall=AdminUserVerificationBreakdown(
                    total=3,
                    statuses={"pending_admin_review": 1, "verified": 2},
                ),
                employments=AdminUserVerificationBreakdown(total=2, statuses={"verified": 2}),
                educations=AdminUserVerificationBreakdown(
                    total=1,
                    statuses={"pending_admin_review": 1},
                ),
                certifications=AdminUserVerificationBreakdown(),
            ),
            verifications=[
                AdminUserVerificationItem(
                    public_id=uuid4(),
                    request_type="employment",
                    status="verified",
                    organization_name="Acme Corp",
                    linked_record_label="Operations Lead at Acme Corp",
                    created_at=now,
                    updated_at=now,
                )
            ],
            passport=AdminUserPassportSummary(
                ready=True,
                active_links=1,
                revoked_links=0,
                expired_links=0,
                total_views=4,
                unique_views=3,
                latest_share_created_at=now,
                last_viewed_at=now,
            ),
            activity=[],
        )


class FakeAdminReviewReadService:
    async def get_evidence_download_url(self, request_id, evidence_id):  # noqa: ANN001
        return AdminEvidenceDownloadResponse(
            evidence_public_id=evidence_id,
            download_url="https://storage.example.test/signed",
            expires_in_seconds=300,
        )


class FakeEmployerVerificationReadService:
    async def get_admin_summary(self, public_id):  # noqa: ANN001
        now = datetime.now(tz=UTC)
        return AdminEmployerVerificationResponse(
            employer_verification=AdminEmployerVerificationSummary(
                public_id=public_id,
                status="pending",
                masked_recipient="h***r@example.com",
                delivery_status="accepted",
                created_at=now,
                updated_at=now,
            )
        )


@pytest.mark.asyncio
async def test_admin_read_contract_routes() -> None:
    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[get_admin_directory_service] = lambda: FakeAdminDirectoryService()
    app.dependency_overrides[get_verification_request_admin_review_service] = (
        lambda: FakeAdminReviewReadService()
    )
    app.dependency_overrides[get_employer_verification_service] = (
        lambda: FakeEmployerVerificationReadService()
    )
    request_id = uuid4()
    evidence_id = uuid4()
    outreach_id = uuid4()
    user_id = uuid4()
    deleted_user_id = UUID("00000000-0000-0000-0000-000000002222")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        reviewers = await client.get("/api/v1/admin/verification-reviewers")
        organizations = await client.get(
            "/api/v1/admin/organizations/search",
            params={"search": "Acme"},
        )
        users = await client.get(
            "/api/v1/admin/users",
            params={"search": "candidate", "page": 1, "page_size": 10},
        )
        user_detail = await client.get(f"/api/v1/admin/users/{user_id}")
        deleted_user_detail = await client.get(f"/api/v1/admin/users/{deleted_user_id}")
        evidence = await client.get(
            f"/api/v1/admin/verification-requests/{request_id}/evidence/{evidence_id}/download-url"
        )
        outreach = await client.get(f"/api/v1/admin/employer-verifications/{outreach_id}")

    app.dependency_overrides.clear()
    assert reviewers.status_code == 200
    assert reviewers.json()["items"][0]["role"] == "hr"
    assert organizations.status_code == 200
    assert organizations.json()["items"][0]["name"] == "Acme Corp"
    assert users.status_code == 200
    assert users.json()["items"][0]["display_name"] == "Candidate One"
    assert users.json()["page_size"] == 10
    assert user_detail.status_code == 200
    assert user_detail.json()["email"] == "candidate.one@example.com"
    assert "password_hash" not in user_detail.text
    assert deleted_user_detail.status_code == 200
    assert deleted_user_detail.json()["display_name"] == "Deleted Candidate"
    assert deleted_user_detail.json()["email"] == "Redacted"
    assert deleted_user_detail.json()["phone"] is None
    assert deleted_user_detail.json()["career_summary"]["total_items"] == 0
    assert evidence.status_code == 200
    assert evidence.json()["evidence_public_id"] == str(evidence_id)
    assert outreach.status_code == 200
    assert outreach.json()["employer_verification"]["public_id"] == str(outreach_id)


@pytest.mark.asyncio
async def test_admin_users_routes_require_authentication_and_permission() -> None:
    user_id = uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        unauthenticated_list = await client.get("/api/v1/admin/users")
        unauthenticated_detail = await client.get(f"/api/v1/admin/users/{user_id}")

    app.dependency_overrides[get_current_user] = _candidate_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        candidate_list = await client.get("/api/v1/admin/users")
        candidate_detail = await client.get(f"/api/v1/admin/users/{user_id}")
    app.dependency_overrides.clear()

    app.dependency_overrides[get_current_user] = _hr_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        hr_list = await client.get("/api/v1/admin/users")
        hr_detail = await client.get(f"/api/v1/admin/users/{user_id}")
    app.dependency_overrides.clear()

    app.dependency_overrides[get_current_user] = _support_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        support_list = await client.get("/api/v1/admin/users")
        support_detail = await client.get(f"/api/v1/admin/users/{user_id}")
    app.dependency_overrides.clear()

    assert unauthenticated_list.status_code == 401
    assert unauthenticated_detail.status_code == 401
    assert candidate_list.status_code == 403
    assert candidate_detail.status_code == 403
    assert hr_list.status_code == 403
    assert hr_detail.status_code == 403
    assert support_list.status_code == 403
    assert support_detail.status_code == 403


@pytest.mark.asyncio
async def test_employer_verification_lookup_uses_verification_request_linkage() -> None:
    outreach = SimpleNamespace(public_id=uuid4())
    result = Mock()
    result.scalar_one_or_none.return_value = outreach
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    repository = EmployerVerificationRepository(session)

    found = await repository.get_by_verification_request_id(uuid4())

    assert found is outreach
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_openapi_exposes_admin_detail_employer_verification_public_id() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    properties = response.json()["components"]["schemas"]["AdminReviewDetailResponse"]["properties"]
    assert "employer_verification_public_id" in properties
