"""Route-contract tests for verification request admin review workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
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
from app.schemas.admin_review_workflow import (
    AdminReviewCycleResponse,
    AdminReviewDetailResponse,
    AdminReviewNoteResponse,
    AdminReviewQueueItemResponse,
    AdminReviewQueueResponse,
    AdminReviewTimelineResponse,
    AdminReviewWorkflowEnvelope,
    AdminVerificationContactReviewRequest,
)
from app.schemas.pagination import ListQueryParams
from app.schemas.verification_request import (
    VerificationRequestCorrectionResponse,
    VerificationRequestEvidenceResponse,
    VerificationRequestResponse,
    VerificationRequestTimelineEventResponse,
    VerificationRequestTimelineResponse,
)
from app.services.verification_request_admin_review_service import (
    VerificationRequestAdminReviewService,
    normalize_contact_review_status,
    normalize_contact_type,
)
from app.services.verification_request_service import VerificationRequestService
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


def _verification_request_response(*, public_id: UUID | None = None) -> VerificationRequestResponse:
    now = datetime.now(tz=UTC)
    return VerificationRequestResponse(
        public_id=public_id or uuid4(),
        origin_type=VerificationRequestOriginType.SUBJECT_INITIATED,
        organization_public_id=None,
        trust_invitation_public_id=None,
        subject_name="Candidate",
        subject_email="candidate@example.com",
        request_type=VerificationRequestType.EMPLOYMENT,
        status=VerificationRequestStatus.PENDING_ADMIN_REVIEW,
        due_date=None,
        trust_context={},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_admin_queue_serializes_reviewer_without_duplicate_response_field() -> None:
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    request = SimpleNamespace(
        id=uuid4(),
        organization_id=None,
        registry_resolution_state="unresolved",
    )
    service._get_required_request = AsyncMock(return_value=request)
    service._reviews = SimpleNamespace(get_latest_review_for_request=AsyncMock(return_value=None))
    service._users = SimpleNamespace(get_by_id=AsyncMock())
    service._contacts = SimpleNamespace(get_current=AsyncMock(return_value=None))

    result = await service._to_queue_item(_verification_request_response())

    assert result.assigned_reviewer is None
    assert result.organization_resolution_status == "unresolved"


@pytest.mark.asyncio
async def test_admin_queue_searches_request_public_id() -> None:
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    response = _verification_request_response()
    queue_item = AdminReviewQueueItemResponse(**response.model_dump())
    service._requests = SimpleNamespace(list_by_status=AsyncMock(return_value=[SimpleNamespace()]))
    service._to_request_response = AsyncMock(return_value=response)
    service._to_queue_item = AsyncMock(return_value=queue_item)

    result = await service.get_queue(
        ListQueryParams(page=1, page_size=10, search=str(response.public_id)[:8])
    )

    assert result.total == 1
    assert result.items == [queue_item]
    service._to_request_response.assert_awaited_once()
    service._to_queue_item.assert_awaited_once_with(response)


@pytest.mark.asyncio
async def test_admin_response_projection_excludes_organization_private_fields() -> None:
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    service._session = object()
    request = SimpleNamespace()
    response = _verification_request_response()

    with patch.object(
        VerificationRequestService,
        "_to_response",
        new=AsyncMock(return_value=response),
    ) as to_response:
        result = await service._to_request_response(request)

    assert result == response
    to_response.assert_awaited_once_with(
        request,
        viewer_user_id=None,
        include_org_private=False,
        apply_consent_filter=False,
    )


@pytest.mark.asyncio
async def test_admin_evidence_projection_excludes_default_download_url() -> None:
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    service._session = object()
    evidence = SimpleNamespace()
    response = SimpleNamespace()

    with patch.object(
        VerificationRequestService,
        "_to_evidence_response",
        new=AsyncMock(return_value=response),
    ) as to_evidence_response:
        result = await service._to_evidence_response(evidence)

    assert result == response
    to_evidence_response.assert_awaited_once_with(evidence, include_download_url=False)


@pytest.mark.asyncio
async def test_admin_evidence_projection_preserves_existing_document_metadata() -> None:
    service = VerificationRequestAdminReviewService.__new__(VerificationRequestAdminReviewService)
    now = datetime.now(tz=UTC)
    evidence = SimpleNamespace(employment_document_id=None)
    service._to_evidence_response = AsyncMock(
        return_value=VerificationRequestEvidenceResponse(
            public_id=uuid4(),
            evidence_type="employment_letter",
            field_key="employment.employer_name",
            document_id=None,
            value=None,
            status="submitted",
            document_type="offer_letter",
            original_filename="offer.pdf",
            mime_type="application/pdf",
            file_size=1024,
            upload_status="uploaded",
            created_at=now,
            updated_at=now,
        )
    )
    result = await service._to_admin_evidence_response(evidence)

    assert result.document_type == "offer_letter"
    assert result.original_filename == "offer.pdf"
    assert result.mime_type == "application/pdf"
    assert result.file_size == 1024
    assert result.upload_status == "uploaded"


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
            consented_at=self._now,
            consent_version="v1",
            consented_fields=["employment_dates"],
            consented_evidence_scope=["employment_letter"],
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

    async def get_queue(self, params=None, priorities=None) -> AdminReviewQueueResponse:
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

    async def finalize(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        return self._request_response(status=VerificationRequestStatus.VERIFIED)

    async def return_to_verifier(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        return self._request_response(status=VerificationRequestStatus.IN_PROGRESS)

    async def cancel(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        return self._request_response(status=VerificationRequestStatus.CANCELLED)

    async def reject(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        return self._request_response(status=VerificationRequestStatus.REJECTED)

    async def unable_to_verify(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        return self._request_response(status=VerificationRequestStatus.UNABLE_TO_VERIFY)

    async def record_clarification_response(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        return self._request_response(status=VerificationRequestStatus.IN_PROGRESS)

    async def change_priority(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        return self._request_response()

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
    assert response.json()["request"]["consented_fields"] == ["employment_dates"]
    assert response.json()["request"]["consented_evidence_scope"] == ["employment_letter"]
    assert response.json()["request"]["consent_version"] == "v1"


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
    app.dependency_overrides[get_current_user] = _override_current_user_factory("admin")
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
    app.dependency_overrides[get_current_user] = _override_current_user_factory("admin")
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
async def test_unable_to_verify_is_available_to_reviewer() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("admin")
    app.dependency_overrides[get_verification_request_admin_review_service] = lambda: (
        FakeVerificationRequestAdminReviewService()
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/admin/verification-requests/{uuid4()}/unable-to-verify",
            json={"decision_summary": "The available evidence cannot be confirmed."},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "unable_to_verify"


@pytest.mark.asyncio
async def test_clarification_response_recording_returns_in_progress() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("admin")
    app.dependency_overrides[get_verification_request_admin_review_service] = lambda: (
        FakeVerificationRequestAdminReviewService()
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/admin/verification-requests/{uuid4()}/record-clarification-response",
            json={"response": "The institution supplied the requested clarification."},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"


@pytest.mark.asyncio
async def test_priority_change_is_restricted_to_admin_manager() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("admin")
    app.dependency_overrides[get_verification_request_admin_review_service] = lambda: (
        FakeVerificationRequestAdminReviewService()
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/admin/verification-requests/{uuid4()}/priority",
            json={"priority": "urgent"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_resolve_organization_returns_pending_organization_acceptance() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("admin")
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
async def test_hr_cannot_dispatch_or_finalize_verification() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("hr")
    app.dependency_overrides[get_verification_request_admin_review_service] = (
        lambda: FakeVerificationRequestAdminReviewService()
    )

    transport = ASGITransport(app=app)
    request_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        approve_response = await client.post(
            f"/api/v1/admin/verification-requests/{request_public_id}/approve",
            json={"decision_summary": "Ready for outreach."},
        )
        finalize_response = await client.post(
            f"/api/v1/admin/verification-requests/{request_public_id}/finalize",
            json={"outcome": "verified", "decision_summary": "Confirmed by the verifier."},
        )
        resolution_response = await client.post(
            f"/api/v1/admin/verification-requests/{request_public_id}/resolve-organization",
            json={"organization_public_id": str(uuid4())},
        )

    app.dependency_overrides.clear()
    assert approve_response.status_code == 403
    assert finalize_response.status_code == 403
    assert resolution_response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_finalize_verification() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory("admin")
    app.dependency_overrides[get_verification_request_admin_review_service] = (
        lambda: FakeVerificationRequestAdminReviewService()
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/admin/verification-requests/{uuid4()}/finalize",
            json={"outcome": "verified", "decision_summary": "Confirmed by the verifier."},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "verified"


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
