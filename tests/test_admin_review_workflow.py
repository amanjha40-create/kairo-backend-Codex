"""Route-contract tests for verification request admin review workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.admin_review.enums import (
    VerificationRequestReviewStatus,
    VerificationReviewCorrectionStatus,
    VerificationReviewNoteType,
    VerificationReviewNoteVisibility,
)
from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_verification_request_admin_review_service
from app.main import app
from app.services.verification_request_admin_review_service import (
    VerificationRequestAdminReviewService,
    normalize_contact_review_status,
    normalize_contact_type,
)
from app.schemas.admin_review_workflow import (
    AdminReviewCycleResponse,
    AdminReviewDetailResponse,
    AdminReviewNoteResponse,
    AdminReviewQueueResponse,
    AdminReviewTimelineResponse,
    AdminReviewWorkflowEnvelope,
    AdminVerificationContactReviewRequest,
)
from app.schemas.verification_request import (
    VerificationRequestCorrectionResponse,
    VerificationRequestEvidenceResponse,
    VerificationRequestResponse,
    VerificationRequestTimelineEventResponse,
    VerificationRequestTimelineResponse,
)
from app.verification_requests.enums import (
    VerificationContactReviewStatus,
    VerificationContactType,
    VerificationRequestEventSource,
    VerificationRequestOriginType,
    VerificationRequestStatus,
    VerificationRequestType,
)


@pytest.mark.parametrize(
    ("review_status", "expected"),
    [
        (VerificationContactReviewStatus.APPROVED, "approved"),
        ("changes_requested", "changes_requested"),
    ],
)
def test_contact_review_status_queue_normalization(review_status, expected) -> None:  # noqa: ANN001
    assert normalize_contact_review_status(review_status) == expected


@pytest.mark.parametrize(
    ("contact_type", "expected"),
    [
        (VerificationContactType.HR, "hr"),
        ("authorized_representative", "authorized_representative"),
    ],
)
def test_contact_type_detail_normalization(contact_type, expected) -> None:  # noqa: ANN001
    assert normalize_contact_type(contact_type) == expected


@pytest.mark.asyncio
async def test_contact_review_refreshes_committed_contact_before_mapping() -> None:
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    service._session = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    request = SimpleNamespace(id=uuid4())
    contact = SimpleNamespace(
        public_id=uuid4(),
        contact_name="Local HR",
        contact_email="hr@example.com",
        contact_role="HR Manager",
        contact_type=VerificationContactType.HR,
        candidate_note=None,
        review_status=VerificationContactReviewStatus.PENDING,
        review_notes=None,
        reviewed_by_user_id=None,
        reviewed_at=None,
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )
    service._require_admin_reviewable_request = AsyncMock(return_value=request)
    service._contacts = SimpleNamespace(get_current=AsyncMock(return_value=contact))
    service._workflow = SimpleNamespace(record_action=AsyncMock())

    response = await service.review_contact(
        uuid4(),
        uuid4(),
        AdminVerificationContactReviewRequest(review_status=VerificationContactReviewStatus.APPROVED),
    )

    service._session.refresh.assert_awaited_once_with(contact)
    assert response.review_status == VerificationContactReviewStatus.APPROVED


class FakeVerificationRequestAdminReviewService:
    def __init__(self, employer_verification_public_id: UUID | None = None) -> None:
        self._request_public_id = uuid4()
        self._review_public_id = uuid4()
        self._evidence_public_id = uuid4()
        self._correction_public_id = uuid4()
        self._event_public_id = uuid4()
        self._now = datetime.now(tz=UTC)
        self._employer_verification_public_id = employer_verification_public_id

    def _request_response(
        self,
        *,
        status: VerificationRequestStatus = VerificationRequestStatus.PENDING_ADMIN_REVIEW,
    ) -> VerificationRequestResponse:
        return VerificationRequestResponse(
            public_id=self._request_public_id,
            origin_type=VerificationRequestOriginType.SUBJECT_INITIATED,
            organization_public_id=None,
            trust_invitation_public_id=None,
            subject_name="Aman Jha",
            subject_email="aman3@test.com",
            target_organization_name="Acme Corp",
            target_organization_email="hr@acme.com",
            request_type=VerificationRequestType.EMPLOYMENT,
            status=status,
            due_date=None,
            trust_context={"source": "subject"},
            created_at=self._now,
            updated_at=self._now,
        )

    def _review_response(
        self,
        *,
        status: VerificationRequestReviewStatus = VerificationRequestReviewStatus.ASSIGNED,
    ) -> AdminReviewCycleResponse:
        return AdminReviewCycleResponse(
            public_id=self._review_public_id,
            review_round=1,
            review_status=status,
            assigned_reviewer_user_id=UUID("00000000-0000-0000-0000-000000000123"),
            assigned_by_user_id=UUID("00000000-0000-0000-0000-000000000999"),
            assigned_at=self._now,
            decision_by_user_id=None,
            decision_at=None,
            decision_summary=None,
            created_at=self._now,
            updated_at=self._now,
        )

    def _evidence_response(self) -> VerificationRequestEvidenceResponse:
        return VerificationRequestEvidenceResponse(
            public_id=self._evidence_public_id,
            evidence_type="employment_letter",
            field_key="employment.company_name",
            document_id=None,
            value={"company_name": "Acme Corp"},
            status="submitted",
            created_at=self._now,
            updated_at=self._now,
        )

    def _correction_response(self) -> VerificationRequestCorrectionResponse:
        return VerificationRequestCorrectionResponse(
            public_id=self._correction_public_id,
            evidence_public_id=self._evidence_public_id,
            field_key="employment.company_name",
            request_text="Please upload a clearer employer letter.",
            guidance={"required": "official_letter"},
            status=VerificationReviewCorrectionStatus.OPEN,
            created_at=self._now,
            updated_at=self._now,
        )

    async def get_queue(self, params=None) -> AdminReviewQueueResponse:
        return AdminReviewQueueResponse(
            items=[self._request_response()],
            total=1,
            page=1,
            page_size=1,
            total_pages=1,
            offset=0,
            limit=1,
        )

    async def get_detail(self, verification_request_public_id):  # noqa: ANN001
        return AdminReviewDetailResponse(
            request=self._request_response(),
            employer_verification_public_id=self._employer_verification_public_id,
            evidence=[],
            reviews=[self._review_response()],
            open_corrections=[self._correction_response()],
        )

    async def assign(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        return AdminReviewWorkflowEnvelope(
            request=self._request_response(),
            review=self._review_response(),
        )

    async def add_note(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        return AdminReviewNoteResponse(
            public_id=uuid4(),
            visibility=VerificationReviewNoteVisibility.INTERNAL,
            note_type=VerificationReviewNoteType.REVIEW_NOTE,
            body=payload.body,
            metadata=payload.metadata,
            created_at=self._now,
            updated_at=self._now,
        )

    async def request_corrections(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        return self._request_response(status=VerificationRequestStatus.AWAITING_SUBJECT_CORRECTIONS)

    async def approve(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        return self._request_response(status=VerificationRequestStatus.PENDING_ORGANIZATION_RESOLUTION)

    async def reject(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        return self._request_response(status=VerificationRequestStatus.REJECTED)

    async def resolve_organization(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        return self._request_response(status=VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE)

    async def get_timeline(self, verification_request_public_id, params=None):  # noqa: ANN001
        return AdminReviewTimelineResponse(
            timeline=VerificationRequestTimelineResponse(
                verification_request_public_id=self._request_public_id,
                items=[
                    VerificationRequestTimelineEventResponse(
                        public_id=self._event_public_id,
                        event_type="verification_request_submitted_for_admin_review",
                        event_source=VerificationRequestEventSource.CANDIDATE,
                        previous_status=VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION,
                        new_status=VerificationRequestStatus.PENDING_ADMIN_REVIEW,
                        metadata={},
                        created_at=self._now,
                    )
                ],
                total=1,
                page=1,
                page_size=1,
                total_pages=1,
                offset=0,
                limit=1,
            )
        )


def _override_current_user_factory(role: str):
    async def _override_current_user() -> CurrentUser:
        return CurrentUser(
            id=UUID("00000000-0000-0000-0000-000000000999"),
            email="reviewer@kairo.test",
            role=role,
        )

    return _override_current_user


@pytest.mark.asyncio
async def test_admin_review_queue_is_available_to_hr() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("hr")
    app.dependency_overrides[get_verification_request_admin_review_service] = (
        lambda: FakeVerificationRequestAdminReviewService()
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/admin/verification-requests/queue")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert response.json()["total"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("employer_verification_public_id", [None, uuid4()])
async def test_admin_review_detail_exposes_employer_verification_public_id(
    employer_verification_public_id: UUID | None,
) -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("hr")
    app.dependency_overrides[get_verification_request_admin_review_service] = lambda: (
        FakeVerificationRequestAdminReviewService(employer_verification_public_id)
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/admin/verification-requests/{uuid4()}")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    expected = str(employer_verification_public_id) if employer_verification_public_id else None
    assert response.json()["employer_verification_public_id"] == expected


@pytest.mark.asyncio
async def test_assign_requires_manager_permission() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("admin")
    app.dependency_overrides[get_verification_request_admin_review_service] = (
        lambda: FakeVerificationRequestAdminReviewService()
    )

    transport = ASGITransport(app=app)
    request_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/admin/verification-requests/{request_public_id}/assign",
            json={"assignee_user_id": str(uuid4())},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["review"]["review_status"] == "assigned"


@pytest.mark.asyncio
async def test_assign_is_forbidden_for_hr() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("hr")
    app.dependency_overrides[get_verification_request_admin_review_service] = (
        lambda: FakeVerificationRequestAdminReviewService()
    )

    transport = ASGITransport(app=app)
    request_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/admin/verification-requests/{request_public_id}/assign",
            json={"assignee_user_id": str(uuid4())},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_request_corrections_updates_request_status() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("hr")
    app.dependency_overrides[get_verification_request_admin_review_service] = (
        lambda: FakeVerificationRequestAdminReviewService()
    )

    transport = ASGITransport(app=app)
    request_public_id = uuid4()
    evidence_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/admin/verification-requests/{request_public_id}/request-corrections",
            json={
                "corrections": [
                    {
                        "evidence_public_id": str(evidence_public_id),
                        "field_key": "employment.company_name",
                        "request_text": "Please upload a clearer employer letter.",
                        "guidance": {"required": "official_letter"},
                    }
                ]
            },
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "awaiting_subject_corrections"


@pytest.mark.asyncio
async def test_approve_returns_approved_for_organization_verification() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("hr")
    app.dependency_overrides[get_verification_request_admin_review_service] = (
        lambda: FakeVerificationRequestAdminReviewService()
    )

    transport = ASGITransport(app=app)
    request_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/admin/verification-requests/{request_public_id}/approve",
            json={"decision_summary": "Evidence is sufficient for outreach."},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "pending_organization_resolution"


@pytest.mark.asyncio
async def test_resolve_organization_returns_pending_organization_acceptance() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("hr")
    app.dependency_overrides[get_verification_request_admin_review_service] = (
        lambda: FakeVerificationRequestAdminReviewService()
    )

    transport = ASGITransport(app=app)
    request_public_id = uuid4()
    organization_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/admin/verification-requests/{request_public_id}/resolve-organization",
            json={"organization_public_id": str(organization_public_id)},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "pending_organization_acceptance"


@pytest.mark.asyncio
async def test_admin_review_timeline_is_available() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("support")
    app.dependency_overrides[get_verification_request_admin_review_service] = (
        lambda: FakeVerificationRequestAdminReviewService()
    )

    transport = ASGITransport(app=app)
    request_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/admin/verification-requests/{request_public_id}/timeline")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["timeline"]["items"][0]["event_type"] == "verification_request_submitted_for_admin_review"
