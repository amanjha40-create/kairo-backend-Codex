"""Public employer portal route and contract regression tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.services import get_employer_verification_service
from app.employment.enums import EmployerVerificationDecision
from app.exceptions import ExpiredLinkError, NotFoundError
from app.main import app
from app.schemas.employer_verification import (
    EmployerPortalActionResponse,
    EmployerPortalCandidate,
    EmployerPortalContact,
    EmployerPortalEmployment,
    EmployerPortalWorkspace,
)


class FakeEmployerPortalService:
    async def get_portal_workspace(self, token: str) -> EmployerPortalWorkspace:
        if token == "missing-token-value":
            raise NotFoundError("This verification link is invalid")
        if token == "expired-token-value":
            raise ExpiredLinkError()
        return EmployerPortalWorkspace(
            employer_verification_public_id=uuid4(),
            state="pending",
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
            candidate=EmployerPortalCandidate(full_name="Candidate One"),
            employment=EmployerPortalEmployment(
                employer_name="Acme",
                job_title="Engineer",
                employment_type="full_time",
                start_date="2024-01-01",
                country="IN",
            ),
            evidence_summary=[],
            employer_contact=EmployerPortalContact(
                contact_name="HR One",
                relationship="hr",
                email_masked="h***r@acme.test",
            ),
            timeline=[],
        )

    async def verify_from_portal(self, token, payload):  # noqa: ANN001
        return EmployerPortalActionResponse(
            employer_verification_public_id=uuid4(),
            decision=EmployerVerificationDecision.CONFIRMED,
            verification_request_status="verified",
            employment_verification_status="approved",
        )

    async def reject_from_portal(self, token, payload):  # noqa: ANN001
        return EmployerPortalActionResponse(
            employer_verification_public_id=uuid4(),
            decision=EmployerVerificationDecision.DECLINED,
            verification_request_status="rejected",
            employment_verification_status="rejected",
        )

    async def request_clarification_from_portal(self, token, payload):  # noqa: ANN001
        return EmployerPortalActionResponse(
            employer_verification_public_id=uuid4(),
            decision=EmployerVerificationDecision.ON_HOLD,
            verification_request_status="awaiting_information",
            employment_verification_status="draft",
        )


@pytest.mark.asyncio
async def test_public_employer_portal_contracts_and_fail_closed_states() -> None:
    app.dependency_overrides[get_employer_verification_service] = lambda: FakeEmployerPortalService()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        workspace = await client.get("/api/v1/public/employer-verifications/valid-token-value")
        missing = await client.get("/api/v1/public/employer-verifications/missing-token-value")
        expired = await client.get("/api/v1/public/employer-verifications/expired-token-value")
        verified = await client.post(
            "/api/v1/public/employer-verifications/valid-token-value/verify",
            json={"employment_existed": True, "dates_correct": True, "role_correct": True},
        )
        rejected = await client.post(
            "/api/v1/public/employer-verifications/valid-token-value/reject",
            json={"reason": "Dates do not match"},
        )
        clarification = await client.post(
            "/api/v1/public/employer-verifications/valid-token-value/request-clarification",
            json={"reason": "Please confirm the end date"},
        )
    app.dependency_overrides.clear()

    assert workspace.status_code == 200
    assert "internal_notes" not in workspace.json()
    assert all("admin_note" not in event["event_type"] for event in workspace.json()["timeline"])
    assert missing.status_code == 404
    assert expired.status_code == 410
    assert verified.json()["verification_request_status"] == "verified"
    assert rejected.json()["decision"] == "declined"
    assert clarification.json()["verification_request_status"] == "awaiting_information"


@pytest.mark.asyncio
async def test_openapi_exposes_employer_portal_actions() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/openapi.json")
    paths = response.json()["paths"]
    assert "/api/v1/public/employer-verifications/{token}" in paths
    assert "/api/v1/public/employer-verifications/{token}/verify" in paths
    assert "/api/v1/public/employer-verifications/{token}/reject" in paths
    assert "/api/v1/public/employer-verifications/{token}/request-clarification" in paths
