"""Route-contract tests for the Organization People Registry."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_organization_person_service
from app.exceptions import ForbiddenError, NotFoundError
from app.main import app
from app.organization_people.enums import (
    OrganizationPersonInvitationStatusSummary,
    OrganizationPersonPassportStatusSummary,
    OrganizationPersonRelationship,
    OrganizationPersonTrustState,
    OrganizationPersonVerificationStatusSummary,
)
from app.schemas.organization_person import (
    OrganizationPeopleDirectorySummary,
    OrganizationPeopleListResponse,
    OrganizationPersonDetailResponse,
    OrganizationPersonEmploymentVerificationResponse,
    OrganizationPersonListItemResponse,
    OrganizationPersonNoteResponse,
    OrganizationPersonPassportPreviewResponse,
    OrganizationPersonRelationshipSummaryResponse,
    OrganizationPersonSummaryCounts,
    OrganizationPersonSummaryResponse,
    OrganizationPersonVerificationSummaryResponse,
)


class FakeOrganizationPersonService:
    def __init__(self) -> None:
        self._org_public_id = uuid4()
        self._person_public_id = uuid4()
        self._note_public_id = uuid4()
        self._request_public_id = uuid4()
        self._now = datetime.now(tz=UTC)

    def _list_item(self) -> OrganizationPersonListItemResponse:
        return OrganizationPersonListItemResponse(
            id=self._person_public_id,
            public_id=self._person_public_id,
            name="Aman Jha",
            full_name="Aman Jha",
            email="aman3@test.com",
            phone="+919999999999",
            relationship=OrganizationPersonRelationship.CANDIDATE,
            trust_state=OrganizationPersonTrustState.PENDING,
            invitation_status=OrganizationPersonInvitationStatusSummary.SENT,
            verification_status=OrganizationPersonVerificationStatusSummary.WAITING_FOR_CANDIDATE,
            passport_status=OrganizationPersonPassportStatusSummary.NOT_SHARED,
            added_by="Owner User",
            added_at=self._now - timedelta(days=2),
            last_activity_at=self._now - timedelta(hours=3),
            summary_counts=OrganizationPersonSummaryCounts(
                invitations=1,
                verification_requests=1,
                shared_evidence_items=0,
                internal_notes=1,
            ),
        )

    def _note(self) -> OrganizationPersonNoteResponse:
        return OrganizationPersonNoteResponse(
            id=self._note_public_id,
            public_id=self._note_public_id,
            author="Owner User",
            author_user_id=uuid4(),
            body="Referral candidate. Awaiting invitation acceptance.",
            at=self._now - timedelta(hours=2),
            created_at=self._now - timedelta(hours=2),
            updated_at=self._now - timedelta(hours=1),
            owned_by_current_user=True,
        )

    def _detail(self) -> OrganizationPersonDetailResponse:
        return OrganizationPersonDetailResponse(
            id=self._person_public_id,
            public_id=self._person_public_id,
            summary=OrganizationPersonSummaryResponse(
                full_name="Aman Jha",
                email="aman3@test.com",
                phone="+919999999999",
                linked_user_id=None,
            ),
            passport_preview=OrganizationPersonPassportPreviewResponse(
                status=OrganizationPersonPassportStatusSummary.NOT_SHARED,
            ),
            verification_summary=OrganizationPersonVerificationSummaryResponse(
                latest_status=OrganizationPersonVerificationStatusSummary.WAITING_FOR_CANDIDATE,
                total_requests=1,
                completed_requests=0,
                active_requests=1,
                clarification_required_requests=0,
            ),
            employment_verifications=[
                OrganizationPersonEmploymentVerificationResponse(
                    id=self._request_public_id,
                    public_id=self._request_public_id,
                    status="waiting_for_candidate",
                    requested_by="Organization member",
                    requested_at=self._now - timedelta(days=1),
                    request_type="employment",
                    request_public_id=self._request_public_id,
                )
            ],
            shared_evidence=[],
            activity=[],
            internal_notes=[self._note()],
            organization_relationship=OrganizationPersonRelationshipSummaryResponse(
                relationship=OrganizationPersonRelationship.CANDIDATE,
                trust_state=OrganizationPersonTrustState.PENDING,
                invitation_status=OrganizationPersonInvitationStatusSummary.SENT,
                verification_status=OrganizationPersonVerificationStatusSummary.WAITING_FOR_CANDIDATE,
                passport_status=OrganizationPersonPassportStatusSummary.NOT_SHARED,
                added_by="Owner User",
                added_at=self._now - timedelta(days=2),
                last_activity_at=self._now - timedelta(hours=3),
                resolution_state="resolved",
                resolution_method="email",
                resolution_confidence=0.95,
                resolution_metadata={"source_type": "trust_invitation"},
            ),
        )

    async def list_for_organization(self, actor_user_id, org_public_id, params):  # noqa: ANN001
        if str(org_public_id) == "00000000-0000-0000-0000-00000000ffff":
            raise ForbiddenError("Organization access is suspended")
        return OrganizationPeopleListResponse(
            items=[self._list_item()],
            total=1,
            page=1,
            page_size=20,
            total_pages=1,
            offset=0,
            limit=20,
            summary=OrganizationPeopleDirectorySummary(
                total_people=1,
                by_relationship={"candidate": 1},
                by_invitation_status={"sent": 1},
                by_verification_status={"waiting_for_candidate": 1},
                by_passport_status={"not_shared": 1},
                by_trust_state={"pending": 1},
            ),
        )

    async def get_detail(self, actor_user_id, org_public_id, person_public_id):  # noqa: ANN001
        if str(person_public_id) == "00000000-0000-0000-0000-00000000eeee":
            raise NotFoundError("Organization person not found")
        return self._detail()

    async def add_note(self, actor_user_id, org_public_id, person_public_id, payload):  # noqa: ANN001
        return self._note()

    async def update_note(self, actor_user_id, org_public_id, person_public_id, note_public_id, payload):  # noqa: ANN001
        return self._note()

    async def delete_note(self, actor_user_id, org_public_id, person_public_id, note_public_id):  # noqa: ANN001
        if str(note_public_id) == "00000000-0000-0000-0000-00000000dddd":
            raise ForbiddenError("Only the note author can delete this note")
        return None


async def _override_current_user() -> CurrentUser:
    return CurrentUser(id=uuid4(), email="owner@kairo.example", role="user")


def test_openapi_exposes_people_registry_paths() -> None:
    schema = app.openapi()["paths"]

    assert "/api/v1/organizations/{org_public_id}/people" in schema
    assert "/api/v1/organizations/{org_public_id}/people/{person_public_id}" in schema
    assert "/api/v1/organizations/{org_public_id}/people/{person_public_id}/notes" in schema


@pytest.mark.asyncio
async def test_list_people_returns_authoritative_directory_summary() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_person_service] = lambda: FakeOrganizationPersonService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/organizations/{org_public_id}/people")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total_people"] == 1
    assert body["items"][0]["relationship"] == "candidate"


@pytest.mark.asyncio
async def test_get_person_detail_returns_backend_composed_sections() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_person_service] = lambda: FakeOrganizationPersonService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    person_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/organizations/{org_public_id}/people/{person_public_id}")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["full_name"] == "Aman Jha"
    assert body["verification_summary"]["total_requests"] == 1
    assert body["organization_relationship"]["resolution_method"] == "email"


@pytest.mark.asyncio
async def test_add_note_returns_created_note() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_person_service] = lambda: FakeOrganizationPersonService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    person_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/organizations/{org_public_id}/people/{person_public_id}/notes",
            json={"body": "Private note"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 201
    assert response.json()["owned_by_current_user"] is True


@pytest.mark.asyncio
async def test_delete_note_maps_forbidden_errors() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_organization_person_service] = lambda: FakeOrganizationPersonService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    person_public_id = uuid4()
    blocked_note_public_id = "00000000-0000-0000-0000-00000000dddd"
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete(
            f"/api/v1/organizations/{org_public_id}/people/{person_public_id}/notes/{blocked_note_public_id}"
        )

    app.dependency_overrides.clear()
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
