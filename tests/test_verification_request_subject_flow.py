"""Route-contract tests for subject verification request and evidence flow."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.admin_review.enums import VerificationRequestEvidenceStatus, VerificationReviewCorrectionStatus
from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_verification_request_service
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.main import app
from app.schemas.verification_request import (
    VerificationRequestCorrectionResponse,
    VerificationRequestEvidenceResponse,
    VerificationRequestResponse,
)
from app.verification_requests.enums import VerificationRequestOriginType, VerificationRequestStatus, VerificationRequestType


class FakeSubjectVerificationRequestService:
    def __init__(self) -> None:
        self._org_public_id = uuid4()
        self._request_public_id = uuid4()
        self._evidence_public_id = uuid4()
        self._correction_public_id = uuid4()
        self._now = datetime.now(tz=UTC)

    def _request_response(
        self,
        *,
        status: VerificationRequestStatus = VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION,
    ) -> VerificationRequestResponse:
        return VerificationRequestResponse(
            public_id=self._request_public_id,
            origin_type=VerificationRequestOriginType.SUBJECT_INITIATED,
            organization_public_id=self._org_public_id,
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

    def _evidence_response(self) -> VerificationRequestEvidenceResponse:
        return VerificationRequestEvidenceResponse(
            public_id=self._evidence_public_id,
            evidence_type="employment_detail",
            field_key="employment.start_date",
            document_id=None,
            value={"start_date": "2024-01-01"},
            status=VerificationRequestEvidenceStatus.SUBMITTED,
            created_at=self._now,
            updated_at=self._now,
        )

    async def create_subject_request(self, actor_user_id, payload):  # noqa: ANN001
        return self._request_response()

    async def list_mine(self, actor_user_id):  # noqa: ANN001
        return [self._request_response()]

    async def list_evidence(self, actor_user_id, actor_email, verification_request_public_id):  # noqa: ANN001
        return [self._evidence_response()]

    async def add_evidence(self, actor_user_id, actor_email, verification_request_public_id, payload):  # noqa: ANN001
        return self._evidence_response()

    async def update_evidence(self, actor_user_id, actor_email, verification_request_public_id, evidence_public_id, payload):  # noqa: ANN001
        return self._evidence_response()

    async def submit_for_review(self, actor_user_id, actor_email, verification_request_public_id):  # noqa: ANN001
        if verification_request_public_id == UUID("00000000-0000-0000-0000-00000000cccc"):
            raise ConflictError("Add at least one evidence item before submitting for review")
        return self._request_response(status=VerificationRequestStatus.PENDING_ADMIN_REVIEW)

    async def list_corrections(self, actor_user_id, actor_email, verification_request_public_id):  # noqa: ANN001
        return [
            VerificationRequestCorrectionResponse(
                public_id=self._correction_public_id,
                evidence_public_id=self._evidence_public_id,
                field_key="employment.start_date",
                request_text="Please attach clearer evidence",
                guidance={"expected": "official letter"},
                status=VerificationReviewCorrectionStatus.OPEN,
                created_at=self._now,
                updated_at=self._now,
            )
        ]

    async def resubmit(self, actor_user_id, actor_email, verification_request_public_id):  # noqa: ANN001
        if verification_request_public_id == UUID("00000000-0000-0000-0000-00000000bbbb"):
            raise ConflictError("There are no open correction requests to resolve")
        return self._request_response(status=VerificationRequestStatus.PENDING_ADMIN_RE_REVIEW)

    async def get_detail(self, actor_user_id, actor_email, verification_request_public_id):  # noqa: ANN001
        return self._request_response()

    async def accept(self, actor_user_id, actor_email, verification_request_public_id):  # noqa: ANN001
        return self._request_response(status=VerificationRequestStatus.ACCEPTED)

    async def request_information(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        raise ForbiddenError("not used")

    async def verify(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        raise ForbiddenError("not used")

    async def reject(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        raise ForbiddenError("not used")

    async def cancel(self, actor_user_id, verification_request_public_id, payload):  # noqa: ANN001
        raise ForbiddenError("not used")

    async def get_timeline(self, actor_user_id, actor_email, verification_request_public_id):  # noqa: ANN001
        raise NotFoundError("not used")


def _override_current_user() -> CurrentUser:
    return CurrentUser(id=uuid4(), email="aman3@test.com", role="user")


@pytest.mark.asyncio
async def test_create_subject_verification_request() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_verification_request_service] = lambda: FakeSubjectVerificationRequestService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/verification-requests",
            json={
                "target_organization_name": "Acme Corp",
                "target_organization_email": "hr@acme.com",
                "request_type": "employment",
                "trust_context": {"source": "subject"},
            },
        )

    app.dependency_overrides.clear()
    assert response.status_code == 201
    assert response.json()["origin_type"] == "subject_initiated"


@pytest.mark.asyncio
async def test_list_my_verification_requests() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_verification_request_service] = lambda: FakeSubjectVerificationRequestService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/verification-requests/me")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert len(response.json()) == 1


@pytest.mark.asyncio
async def test_add_evidence() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_verification_request_service] = lambda: FakeSubjectVerificationRequestService()

    transport = ASGITransport(app=app)
    request_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/verification-requests/{request_public_id}/evidence",
            json={
                "evidence_type": "employment_detail",
                "field_key": "employment.start_date",
                "value": {"start_date": "2024-01-01"},
            },
        )

    app.dependency_overrides.clear()
    assert response.status_code == 201
    assert response.json()["field_key"] == "employment.start_date"


@pytest.mark.asyncio
async def test_submit_for_review() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_verification_request_service] = lambda: FakeSubjectVerificationRequestService()

    transport = ASGITransport(app=app)
    request_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/v1/verification-requests/{request_public_id}/submit-for-review")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "pending_admin_review"


@pytest.mark.asyncio
async def test_submit_for_review_requires_evidence() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_verification_request_service] = lambda: FakeSubjectVerificationRequestService()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/verification-requests/00000000-0000-0000-0000-00000000cccc/submit-for-review")

    app.dependency_overrides.clear()
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_list_corrections() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_verification_request_service] = lambda: FakeSubjectVerificationRequestService()

    transport = ASGITransport(app=app)
    request_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/verification-requests/{request_public_id}/corrections")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()[0]["status"] == "open"


@pytest.mark.asyncio
async def test_resubmit_request() -> None:
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_verification_request_service] = lambda: FakeSubjectVerificationRequestService()

    transport = ASGITransport(app=app)
    request_public_id = uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/v1/verification-requests/{request_public_id}/resubmit")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "pending_admin_re_review"
