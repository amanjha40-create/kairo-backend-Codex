"""Route contracts for additive Admin review read APIs."""

from datetime import UTC, datetime
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
from app.schemas.admin_directory import (
    AdminOrganizationSearchItem,
    AdminOrganizationSearchPage,
    AdminReviewerPage,
    AdminReviewerResponse,
)
from app.schemas.admin_review_workflow import AdminEvidenceDownloadResponse
from app.schemas.employer_verification import (
    AdminEmployerVerificationResponse,
    AdminEmployerVerificationSummary,
)


async def _admin_user() -> CurrentUser:
    return CurrentUser(
        id=UUID("00000000-0000-0000-0000-000000000999"),
        email="admin@kairo.test",
        role="admin",
    )


class FakeAdminDirectoryService:
    async def list_reviewers(self, params):  # noqa: ANN001
        return AdminReviewerPage.create(
            items=[AdminReviewerResponse(user_id=uuid4(), full_name="Reviewer", email="reviewer@kairo.test", role="hr")],
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
    app.dependency_overrides[get_verification_request_admin_review_service] = lambda: FakeAdminReviewReadService()
    app.dependency_overrides[get_employer_verification_service] = lambda: FakeEmployerVerificationReadService()
    request_id = uuid4()
    evidence_id = uuid4()
    outreach_id = uuid4()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        reviewers = await client.get("/api/v1/admin/verification-reviewers")
        organizations = await client.get("/api/v1/admin/organizations/search", params={"search": "Acme"})
        evidence = await client.get(
            f"/api/v1/admin/verification-requests/{request_id}/evidence/{evidence_id}/download-url"
        )
        outreach = await client.get(f"/api/v1/admin/employer-verifications/{outreach_id}")

    app.dependency_overrides.clear()
    assert reviewers.status_code == 200
    assert reviewers.json()["items"][0]["role"] == "hr"
    assert organizations.status_code == 200
    assert organizations.json()["items"][0]["name"] == "Acme Corp"
    assert evidence.status_code == 200
    assert evidence.json()["evidence_public_id"] == str(evidence_id)
    assert outreach.status_code == 200
    assert outreach.json()["employer_verification"]["public_id"] == str(outreach_id)
