"""Route-contract tests for verification request engine endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_verification_request_service
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.main import app
from app.schemas.pagination import filter_sort_paginate
from app.schemas.verification_request import (
    VerificationRequestAssignReviewerRequest,
    VerificationRequestCreateRequest,
    VerificationRequestInternalNoteUpdateRequest,
    VerificationRequestResponse,
    VerificationRequestTimelineEventResponse,
    VerificationRequestTimelineResponse,
)
from app.services.verification_request_service import (
    VerificationRequestService,
    is_internal_admin_note_event,
    is_private_organization_event,
)
from app.verification_requests.enums import (
    VerificationRequestEventSource,
    VerificationRequestStatus,
    VerificationRequestType,
)


def test_internal_admin_note_events_are_private_to_admin_timeline() -> None:
    assert is_internal_admin_note_event(
        "verification_request_admin_note_added",
        {"visibility": "internal", "note_public_id": str(uuid4())},
    )
    assert not is_internal_admin_note_event("admin_requested_corrections", {"visibility": "candidate"})


def test_private_organization_events_are_hidden_from_subject_timeline() -> None:
    assert is_private_organization_event(
        "verification_request_internal_note_updated",
        {"visibility": "organization_internal"},
    )
    assert is_private_organization_event(
        "verification_request_reviewer_assigned",
        {},
    )
    assert not is_private_organization_event("verification_request_verified", {})


def test_assign_reviewer_request_accepts_organization_member_public_id() -> None:
    member_public_id = uuid4()

    payload = VerificationRequestAssignReviewerRequest(
        organization_member_public_id=member_public_id,
    )

    assert payload.organization_member_public_id == member_public_id
    assert payload.assignee_user_id is None


def test_assign_reviewer_request_rejects_both_member_and_user_identifiers() -> None:
    with pytest.raises(ValueError, match="Provide only one of"):
        VerificationRequestAssignReviewerRequest(
            organization_member_public_id=uuid4(),
            assignee_user_id=uuid4(),
        )


def test_openapi_exposes_membership_based_reviewer_assignment() -> None:
    schema = app.openapi()["components"]["schemas"]["VerificationRequestAssignReviewerRequest"]
    properties = schema["properties"]

    assert "organization_member_public_id" in properties
    assert "assignee_user_id" in properties


def test_organization_employment_verification_requires_one_canonical_employment_id() -> None:
    employment_id = uuid4()

    payload = VerificationRequestCreateRequest(
        subject_name="Candidate",
        subject_email="candidate@example.com",
        request_type=VerificationRequestType.EMPLOYMENT,
        employment_id=employment_id,
    )

    assert payload.employment_id == employment_id
    assert payload.education_id is None
    with pytest.raises(ValueError, match="Employment verification requires employment_id only"):
        VerificationRequestCreateRequest(
            subject_name="Candidate",
            subject_email="candidate@example.com",
            request_type=VerificationRequestType.EMPLOYMENT,
        )


def test_organization_education_verification_requires_one_canonical_education_id() -> None:
    education_id = uuid4()

    payload = VerificationRequestCreateRequest(
        subject_name="Candidate",
        subject_email="candidate@example.com",
        request_type=VerificationRequestType.EDUCATION,
        education_id=education_id,
    )

    assert payload.education_id == education_id
    assert payload.employment_id is None
    with pytest.raises(ValueError, match="Education verification requires education_id only"):
        VerificationRequestCreateRequest(
            subject_name="Candidate",
            subject_email="candidate@example.com",
            request_type=VerificationRequestType.EDUCATION,
        )


@pytest.mark.asyncio
async def test_organization_employment_verification_resolves_the_owned_career_record() -> None:
    employment_id = uuid4()
    subject_user_id = uuid4()
    employment = SimpleNamespace(id=employment_id)
    service = VerificationRequestService.__new__(VerificationRequestService)
    service._employments = SimpleNamespace(get_owned_active=AsyncMock(return_value=employment))
    service._requests = SimpleNamespace(get_active_for_employment=AsyncMock(return_value=None))

    resolved_employment, resolved_education = await service._resolve_organization_claim(
        payload=VerificationRequestCreateRequest(
            subject_name="Candidate",
            subject_email="candidate@example.com",
            request_type=VerificationRequestType.EMPLOYMENT,
            employment_id=employment_id,
        ),
        subject_user_id=subject_user_id,
    )

    assert resolved_employment is employment
    assert resolved_education is None
    service._employments.get_owned_active.assert_awaited_once_with(employment_id, subject_user_id)
    service._requests.get_active_for_employment.assert_awaited_once_with(employment_id)


@pytest.mark.asyncio
async def test_organization_employment_verification_rejects_an_active_duplicate() -> None:
    employment_id = uuid4()
    service = VerificationRequestService.__new__(VerificationRequestService)
    service._employments = SimpleNamespace(get_owned_active=AsyncMock(return_value=SimpleNamespace(id=employment_id)))
    service._requests = SimpleNamespace(get_active_for_employment=AsyncMock(return_value=SimpleNamespace()))

    with pytest.raises(ConflictError, match="active verification request"):
        await service._resolve_organization_claim(
            payload=VerificationRequestCreateRequest(
                subject_name="Candidate",
                subject_email="candidate@example.com",
                request_type=VerificationRequestType.EMPLOYMENT,
                employment_id=employment_id,
            ),
            subject_user_id=uuid4(),
        )


class FakeVerificationRequestService:
    def __init__(self) -> None:
        self._org_public_id = uuid4()
        self._request_public_id = uuid4()
        self._invitation_public_id = uuid4()
        self._event_public_id = uuid4()
        self._now = datetime.now(tz=UTC)

    def _response(
        self,
        status: VerificationRequestStatus = VerificationRequestStatus.PENDING_SUBJECT_ACCEPTANCE,
    ) -> VerificationRequestResponse:
        return VerificationRequestResponse(
            public_id=self._request_public_id,
            organization_public_id=self._org_public_id,
            trust_invitation_public_id=self._invitation_public_id,
            subject_name="Aman Jha",
            subject_email="aman3@test.com",
            request_type=VerificationRequestType.EMPLOYMENT,
            status=status,
            due_date=None,
            trust_context={"source": "api"},
            created_at=self._now,
            updated_at=self._now,
        )

    async def create(self, actor_user_id, organization_public_id, payload):  # noqa: ANN001
        return self._response()

    async def list_for_organization(self, actor_user_id, organization_public_id, params=None):  # noqa: ANN001
        if organization_public_id == UUID("00000000-0000-0000-0000-00000000ffff"):
            raise NotFoundError("Organization not found")
        items = [self._response(), self._response(VerificationRequestStatus.ACCEPTED)]
        if params:
            return filter_sort_paginate(
                items,
                params=params,
                search_fields=(
                    "subject_name",
                    "subject_email",
                    "request_type",
                    "status",
                ),
                allowed_sort_fields=("created_at", "updated_at", "subject_name", "subject_email", "request_type", "status"),
                default_sort_by="created_at",
            )
        return items

    async def get_detail(self, actor_user_id, actor_email, verification_request_public_id):  # noqa: ANN001
        if verification_request_public_id == UUID("00000000-0000-0000-0000-00000000ffff"):
            raise NotFoundError("Verification request not found")
        return self._response(VerificationRequestStatus.ACCEPTED)

    async def assign_reviewer(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        assert isinstance(payload, VerificationRequestAssignReviewerRequest)
        return self._response(VerificationRequestStatus.ACCEPTED)

    async def update_internal_note(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        assert isinstance(payload, VerificationRequestInternalNoteUpdateRequest)
        return self._response(VerificationRequestStatus.ACCEPTED)

    async def accept(self, actor_user_id, actor_email, verification_request_public_id):  # noqa: ANN001
        if verification_request_public_id == UUID("00000000-0000-0000-0000-00000000eeee"):
            raise ConflictError("Verification request is already in the requested status")
        if actor_email == "owner@example.com":
            raise ForbiddenError("Only the request subject can accept this verification request")
        return self._response(VerificationRequestStatus.ACCEPTED)

    async def request_information(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        return self._response(VerificationRequestStatus.AWAITING_INFORMATION)

    async def verify(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        if verification_request_public_id == UUID("00000000-0000-0000-0000-00000000dddd"):
            raise ConflictError("Verification request cannot transition from verified to verified")
        if actor_user_id == UUID("00000000-0000-0000-0000-000000000111"):
            raise ForbiddenError("The request subject cannot perform this action")
        return self._response(VerificationRequestStatus.VERIFIED)

    async def reject(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        return self._response(VerificationRequestStatus.REJECTED)

    async def cancel(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        return self._response(VerificationRequestStatus.CANCELLED)

    async def get_timeline(self, actor_user_id, actor_email, verification_request_public_id, params=None):  # noqa: ANN001
        return VerificationRequestTimelineResponse(
            verification_request_public_id=self._request_public_id,
            items=[
                VerificationRequestTimelineEventResponse(
                    public_id=self._event_public_id,
                    event_type="verification_request_created",
                    event_source=VerificationRequestEventSource.ORGANIZATION,
                    previous_status=None,
                    new_status=VerificationRequestStatus.PENDING_SUBJECT_ACCEPTANCE,
                    metadata={"request_type": "employment"},
                    created_at=self._now,
                ),
                VerificationRequestTimelineEventResponse(
                    public_id=uuid4(),
                    event_type="verification_request_subject_accepted",
                    event_source=VerificationRequestEventSource.CANDIDATE,
                    previous_status=VerificationRequestStatus.PENDING_SUBJECT_ACCEPTANCE,
                    new_status=VerificationRequestStatus.ACCEPTED,
                    metadata={},
                    created_at=self._now,
                ),
            ],
            total=2,
            page=1,
            page_size=2,
            total_pages=1,
            offset=0,
            limit=2,
        )


def _override_current_user_factory(
    *,
    email: str,
    user_id: UUID | None = None,
):
    async def _override_current_user() -> CurrentUser:
        return CurrentUser(id=user_id or uuid4(), email=email, role="user")

    return _override_current_user


@pytest.mark.asyncio
async def test_create_verification_request_returns_pending_subject_acceptance() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory(email="owner@example.com")
    app.dependency_overrides[get_verification_request_service] = lambda: FakeVerificationRequestService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/organizations/{org_public_id}/verification-requests",
            json={
                "subject_name": "Aman Jha",
                "subject_email": "aman3@test.com",
                "request_type": "identity",
                "trust_context": {"source": "api"},
            },
        )

    app.dependency_overrides.clear()
    assert response.status_code == 201
    assert response.json()["status"] == "pending_subject_acceptance"


@pytest.mark.asyncio
async def test_list_verification_requests_returns_items() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory(email="member@example.com")
    app.dependency_overrides[get_verification_request_service] = lambda: FakeVerificationRequestService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/organizations/{org_public_id}/verification-requests")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert len(response.json()) == 2


@pytest.mark.asyncio
async def test_list_verification_requests_supports_paginated_mode() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory(email="member@example.com")
    app.dependency_overrides[get_verification_request_service] = lambda: FakeVerificationRequestService()

    transport = ASGITransport(app=app)
    org_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/organizations/{org_public_id}/verification-requests?paginate=true&page=1&page_size=1"
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert len(response.json()["items"]) == 1


@pytest.mark.asyncio
async def test_non_member_cannot_list_verification_requests() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory(email="outsider@example.com")
    app.dependency_overrides[get_verification_request_service] = lambda: FakeVerificationRequestService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/organizations/00000000-0000-0000-0000-00000000ffff/verification-requests")

    app.dependency_overrides.clear()
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_subject_can_read_request_detail() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory(email="aman3@test.com")
    app.dependency_overrides[get_verification_request_service] = lambda: FakeVerificationRequestService()

    transport = ASGITransport(app=app)
    request_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/verification-requests/{request_public_id}")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_org_member_can_assign_verification_request_reviewer() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory(email="member@example.com")
    app.dependency_overrides[get_verification_request_service] = lambda: FakeVerificationRequestService()

    transport = ASGITransport(app=app)
    request_public_id = uuid4()
    member_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(
            f"/api/v1/verification-requests/{request_public_id}/reviewer",
            json={"organization_member_public_id": str(member_public_id)},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_org_member_can_assign_verification_request_reviewer_with_legacy_user_identifier() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory(email="member@example.com")
    app.dependency_overrides[get_verification_request_service] = lambda: FakeVerificationRequestService()

    transport = ASGITransport(app=app)
    request_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(
            f"/api/v1/verification-requests/{request_public_id}/reviewer",
            json={"assignee_user_id": str(uuid4())},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_assign_reviewer_rejects_conflicting_member_and_user_identifiers() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory(email="member@example.com")
    app.dependency_overrides[get_verification_request_service] = lambda: FakeVerificationRequestService()

    transport = ASGITransport(app=app)
    request_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(
            f"/api/v1/verification-requests/{request_public_id}/reviewer",
            json={
                "organization_member_public_id": str(uuid4()),
                "assignee_user_id": str(uuid4()),
            },
        )

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.asyncio
async def test_org_member_can_update_verification_request_internal_note() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory(email="member@example.com")
    app.dependency_overrides[get_verification_request_service] = lambda: FakeVerificationRequestService()

    transport = ASGITransport(app=app)
    request_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(
            f"/api/v1/verification-requests/{request_public_id}/internal-note",
            json={"note": "Cross-check against HRIS before responding."},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_subject_can_accept_request() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory(email="aman3@test.com")
    app.dependency_overrides[get_verification_request_service] = lambda: FakeVerificationRequestService()

    transport = ASGITransport(app=app)
    request_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/v1/verification-requests/{request_public_id}/accept")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_duplicate_accept_is_rejected() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory(email="aman3@test.com")
    app.dependency_overrides[get_verification_request_service] = lambda: FakeVerificationRequestService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/verification-requests/00000000-0000-0000-0000-00000000eeee/accept")

    app.dependency_overrides.clear()
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


@pytest.mark.asyncio
async def test_organization_actor_cannot_use_subject_accept_route() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory(email="owner@example.com")
    app.dependency_overrides[get_verification_request_service] = lambda: FakeVerificationRequestService()

    transport = ASGITransport(app=app)
    request_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/v1/verification-requests/{request_public_id}/accept")

    app.dependency_overrides.clear()
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_verify_request_returns_verified_status() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory(email="owner@example.com")
    app.dependency_overrides[get_verification_request_service] = lambda: FakeVerificationRequestService()

    transport = ASGITransport(app=app)
    request_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/verification-requests/{request_public_id}/verify",
            json={"note": "All evidence validated", "metadata": {"source": "manual-review"}},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "verified"


@pytest.mark.asyncio
async def test_subject_cannot_verify_request() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory(
        email="aman3@test.com",
        user_id=UUID("00000000-0000-0000-0000-000000000111"),
    )
    app.dependency_overrides[get_verification_request_service] = lambda: FakeVerificationRequestService()

    transport = ASGITransport(app=app)
    request_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/verification-requests/{request_public_id}/verify",
            json={"note": "Trying to self-verify"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_invalid_workflow_transition_is_rejected() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory(email="owner@example.com")
    app.dependency_overrides[get_verification_request_service] = lambda: FakeVerificationRequestService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/verification-requests/00000000-0000-0000-0000-00000000dddd/verify",
            json={},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_subject_can_view_own_timeline() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user_factory(email="aman3@test.com")
    app.dependency_overrides[get_verification_request_service] = lambda: FakeVerificationRequestService()

    transport = ASGITransport(app=app)
    request_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/verification-requests/{request_public_id}/timeline")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert body["items"][0]["event_type"] == "verification_request_created"
    assert body["total"] == 2
