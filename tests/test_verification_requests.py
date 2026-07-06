"""Route-contract tests for verification request engine endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_verification_request_service
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.main import app
from app.schemas.pagination import filter_sort_paginate
from app.schemas.verification_request import (
    VerificationRequestResponse,
    VerificationRequestTimelineEventResponse,
    VerificationRequestTimelineResponse,
)
from app.verification_requests.enums import (
    VerificationRequestEventSource,
    VerificationRequestStatus,
    VerificationRequestType,
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
                "request_type": "employment",
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
