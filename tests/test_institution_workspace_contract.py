"""Route and privacy contracts for the institution workspace projections."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_institution_workspace_service
from app.institution_people.enums import (
    InstitutionCredentialStatus,
    InstitutionPersonLifecycleStatus,
    InstitutionVerificationStatus,
)
from app.main import app
from app.schemas.account_settings import AccountSessionResponse
from app.schemas.institution_people import InstitutionPeriod
from app.schemas.institution_workspace import (
    InstitutionAuthoritativeRecord,
    InstitutionCandidateEducationClaim,
    InstitutionDashboardResponse,
    InstitutionPassportCredentialSummary,
    InstitutionPassportSummaryResponse,
    InstitutionVerificationComparison,
    InstitutionVerificationDetailResponse,
    InstitutionVerificationInboxItem,
    InstitutionVerificationInboxQuery,
    InstitutionVerificationInboxResponse,
)
from app.verification_requests.enums import VerificationRequestStatus, VerificationRequestType


class FakeInstitutionWorkspaceService:
    def __init__(self) -> None:
        self.organization_public_id = uuid4()
        self.request_public_id = uuid4()
        self.person_public_id = uuid4()
        self.now = datetime.now(tz=UTC)
        self.cancelled = False

    def _item(self) -> InstitutionVerificationInboxItem:
        return InstitutionVerificationInboxItem(
            public_id=self.request_public_id,
            subject_name="Synthetic Student",
            request_type=VerificationRequestType.EDUCATION,
            status=VerificationRequestStatus.IN_PROGRESS,
            priority="high",
            created_at=self.now,
            updated_at=self.now,
            education_institution_name="Kairo University",
            education_degree="BSc",
        )

    def _detail(self) -> InstitutionVerificationDetailResponse:
        return InstitutionVerificationDetailResponse(
            **self._item().model_dump(),
            comparison=InstitutionVerificationComparison(
                match_status="partial",
                candidate_claim=InstitutionCandidateEducationClaim(
                    institution_name="Kairo University", degree="BSc"
                ),
                institution_record=InstitutionAuthoritativeRecord(
                    found=True, degree="BSc", programme="Computer Science"
                ),
            ),
        )

    async def dashboard(self, actor_user_id, org_public_id):  # noqa: ANN001
        assert actor_user_id
        assert org_public_id == self.organization_public_id
        return InstitutionDashboardResponse(pending_verifications=1)

    async def list_verifications(self, actor_user_id, org_public_id, params):  # noqa: ANN001
        assert actor_user_id
        assert org_public_id == self.organization_public_id
        assert params.priority in {None, "high"}
        return InstitutionVerificationInboxResponse.create(
            items=[self._item()], total=1, params=params
        )

    async def verification_detail(self, actor_user_id, org_public_id, request_public_id):  # noqa: ANN001
        assert actor_user_id
        assert org_public_id == self.organization_public_id
        assert request_public_id == self.request_public_id
        return self._detail()

    async def cancel_verification(self, actor_user_id, org_public_id, request_public_id, payload):  # noqa: ANN001
        assert actor_user_id
        assert org_public_id == self.organization_public_id
        assert request_public_id == self.request_public_id
        assert payload.note == "Duplicate request"
        self.cancelled = True
        detail = self._detail()
        detail.status = VerificationRequestStatus.CANCELLED
        return detail

    async def change_priority(self, actor_user_id, org_public_id, request_public_id, priority):  # noqa: ANN001
        assert actor_user_id
        assert org_public_id == self.organization_public_id
        assert request_public_id == self.request_public_id
        assert priority == "urgent"
        detail = self._detail()
        detail.priority = "urgent"
        return detail

    async def passport_summary(self, actor_user_id, org_public_id, person_public_id):  # noqa: ANN001
        assert actor_user_id
        assert org_public_id == self.organization_public_id
        assert person_public_id == self.person_public_id
        return InstitutionPassportSummaryResponse(
            person_public_id=self.person_public_id,
            display_name="Synthetic Student",
            lifecycle_status=InstitutionPersonLifecycleStatus.ALUMNI,
            verification_status=InstitutionVerificationStatus.VERIFIED,
            credentials=[
                InstitutionPassportCredentialSummary(
                    public_id=uuid4(),
                    title="Bachelor of Science",
                    credential_type="degree",
                    status=InstitutionCredentialStatus.ISSUED,
                    issued=InstitutionPeriod(period="2024"),
                )
            ],
        )


def _override_current_user() -> CurrentUser:
    return CurrentUser(id=uuid4(), email="institution@example.test", role="user")


@pytest.mark.asyncio
async def test_institution_workspace_routes_are_authenticated_and_allowlisted() -> None:
    service = FakeInstitutionWorkspaceService()
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_institution_workspace_service] = lambda: service
    prefix = f"/api/v1/organizations/{service.organization_public_id}/institution"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        dashboard = await client.get(f"{prefix}/dashboard")
        inbox = await client.get(
            f"{prefix}/verification-requests?priority=high&page=1&page_size=10"
        )
        detail = await client.get(f"{prefix}/verification-requests/{service.request_public_id}")
        cancelled = await client.post(
            f"{prefix}/verification-requests/{service.request_public_id}/cancel",
            json={"note": "Duplicate request"},
        )
        priority = await client.patch(
            f"{prefix}/verification-requests/{service.request_public_id}/priority",
            json={"priority": "urgent"},
        )
        passport = await client.get(f"{prefix}/people/{service.person_public_id}/passport-summary")

    app.dependency_overrides.clear()
    assert dashboard.status_code == 200
    assert dashboard.json()["pending_verifications"] == 1
    assert inbox.status_code == 200
    assert inbox.json()["total"] == 1
    assert detail.status_code == 200
    assert detail.json()["comparison"]["match_status"] == "partial"
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert service.cancelled is True
    assert priority.status_code == 200
    assert priority.json()["priority"] == "urgent"
    assert passport.status_code == 200
    body = passport.json()
    assert body["display_name"] == "Synthetic Student"
    assert "trust_score" not in body
    assert "email" not in body
    assert "phone" not in body
    assert "address" not in body


@pytest.mark.asyncio
async def test_institution_workspace_routes_reject_unauthenticated_requests() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/organizations/{uuid4()}/institution/dashboard")
    assert response.status_code == 401


def test_inbox_supports_search_filters_sorting_and_priority() -> None:
    query = InstitutionVerificationInboxQuery(
        search="synthetic",
        status="in_progress,awaiting_information",
        priority="urgent",
        request_type="education",
        assigned_to_me=True,
        sort_by="priority",
        sort_order="asc",
        page=2,
        page_size=10,
    )
    assert query.statuses == {"in_progress", "awaiting_information"}
    assert query.slice_start == 10
    assert query.priority == "urgent"


def test_passport_summary_contract_is_not_a_full_passport() -> None:
    fields = set(InstitutionPassportSummaryResponse.model_fields)
    forbidden = {"passport", "trust_score", "email", "phone", "date_of_birth", "address"}
    assert fields.isdisjoint(forbidden)


def test_account_session_metadata_is_optional_when_not_collected() -> None:
    session = AccountSessionResponse(
        id=uuid4(),
        created_at=datetime.now(tz=UTC),
        expires_at=datetime.now(tz=UTC),
        last_active_at=datetime.now(tz=UTC),
    )
    assert session.device is None
    assert session.browser is None
    assert session.location is None


def test_openapi_exposes_institution_workspace_contract() -> None:
    paths = app.openapi()["paths"]
    prefix = "/api/v1/organizations/{org_public_id}/institution"
    assert f"{prefix}/dashboard" in paths
    assert f"{prefix}/verification-requests" in paths
    assert f"{prefix}/verification-requests/{{request_public_id}}" in paths
    assert f"{prefix}/verification-requests/{{request_public_id}}/cancel" in paths
    assert f"{prefix}/verification-requests/{{request_public_id}}/priority" in paths
    assert f"{prefix}/people/{{person_public_id}}/passport-summary" in paths
