"""Public institution magic-link contract and service regressions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.services import get_public_institution_verification_service
from app.exceptions import ConflictError, ValidationAppError
from app.main import app
from app.schemas.public_institution_verification import (
    PublicInstitutionVerificationCandidateClaim,
    PublicInstitutionVerificationClarificationRequest,
    PublicInstitutionVerificationConfirmRequest,
    PublicInstitutionVerificationEvidenceFile,
    PublicInstitutionVerificationReadResponse,
    PublicInstitutionVerificationRequestProjection,
)
from app.services.public_institution_verification_service import (
    PublicInstitutionVerificationService,
)
from app.verification_requests.enums import VerificationRequestStatus, VerificationRequestType


class FakePublicInstitutionVerificationService:
    def __init__(self) -> None:
        self.now = datetime.now(tz=UTC)

    def _response(self, state: str) -> PublicInstitutionVerificationReadResponse:
        return PublicInstitutionVerificationReadResponse(
            token="valid-token-value",
            state=state,  # type: ignore[arg-type]
            expires_at=self.now + timedelta(hours=72),
            request=(
                PublicInstitutionVerificationRequestProjection(
                    reference="VR-1234ABCD",
                    requested_by="Institution Acceptance University",
                    purpose="Education verification request",
                    request_date=self.now,
                    consent_received=True,
                    candidate=PublicInstitutionVerificationCandidateClaim(
                        candidate_name="Synthetic Student",
                        student_id="STU-42",
                        institution_name="Kairo University",
                        degree="BSc",
                        programme="Computer Science",
                        department="Engineering",
                        admission_year="2020",
                        graduation_year="2024",
                        completion_status="completed",
                    ),
                    evidence=[
                        PublicInstitutionVerificationEvidenceFile(
                            id=str(uuid4()),
                            name="transcript.pdf",
                            type="transcript",
                            uploaded_by="Request subject",
                            uploaded_at=self.now,
                            url="https://example.test/evidence.pdf",
                        )
                    ],
                )
                if state == "valid"
                else None
            ),
        )

    async def get_public_request(self, token: str) -> PublicInstitutionVerificationReadResponse:
        if token == "expired-token-value":
            return self._response("expired")
        if token == "revoked-token-value":
            return self._response("revoked")
        if token == "completed-token-value":
            return self._response("completed")
        if token == "missing-token-value":
            return PublicInstitutionVerificationReadResponse(token=token, state="invalid")
        return self._response("valid")

    async def confirm_from_public(self, token, payload):  # noqa: ANN001
        assert payload.note is None or isinstance(payload.note, str)
        return self._response("completed")

    async def report_discrepancy_from_public(self, token, payload):  # noqa: ANN001
        assert payload.fields
        return self._response("completed")

    async def request_clarification_from_public(self, token, payload):  # noqa: ANN001
        assert payload.request_document is True
        return self._response("completed")


class _LazyOrganizationRequest:
    def __init__(self) -> None:
        self.id = uuid4()
        self.public_id = uuid4()
        self.education_id = uuid4()
        self.target_organization_name = "Institution Acceptance University"
        self.subject_name = "Synthetic Student"
        self.request_type = VerificationRequestType.EDUCATION
        self.created_at = datetime.now(tz=UTC)
        self.consented_at = datetime.now(tz=UTC)
        self.candidate_response = "Candidate supplied note"

    @property
    def organization(self):  # pragma: no cover - defensive trap
        raise AssertionError("public projection must not lazy-load request.organization")


@pytest.mark.asyncio
async def test_public_institution_route_contract_and_fail_closed_states() -> None:
    app.dependency_overrides[get_public_institution_verification_service] = (
        lambda: FakePublicInstitutionVerificationService()
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        valid = await client.get("/api/v1/public/institution-verifications/valid-token-value")
        invalid = await client.get("/api/v1/public/institution-verifications/missing-token-value")
        expired = await client.get("/api/v1/public/institution-verifications/expired-token-value")
        revoked = await client.get("/api/v1/public/institution-verifications/revoked-token-value")
        confirm = await client.post(
            "/api/v1/public/institution-verifications/valid-token-value/confirm",
            json={"note": "Records match our files."},
        )
        discrepancy = await client.post(
            "/api/v1/public/institution-verifications/valid-token-value/report-discrepancy",
            json={"fields": ["graduation_year"], "explanation": "Graduation year differs."},
        )
        clarification = await client.post(
            "/api/v1/public/institution-verifications/valid-token-value/request-clarification",
            json={
                "fields": ["student_id"],
                "message": "Please share the student identifier used internally.",
                "request_document": True,
            },
        )
    app.dependency_overrides.clear()

    assert valid.status_code == 200
    assert valid.json()["state"] == "valid"
    assert "trust_score" not in valid.text
    assert "admin_note" not in valid.text
    assert invalid.status_code == 200
    assert invalid.json()["state"] == "invalid"
    assert expired.status_code == 200
    assert expired.json()["state"] == "expired"
    assert revoked.status_code == 200
    assert revoked.json()["state"] == "revoked"
    assert confirm.status_code == 200
    assert confirm.json()["state"] == "completed"
    assert discrepancy.status_code == 200
    assert discrepancy.json()["state"] == "completed"
    assert clarification.status_code == 200
    assert clarification.json()["state"] == "completed"


def test_openapi_exposes_public_institution_verification_contract() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/public/institution-verifications/{token}" in paths
    assert "/api/v1/public/institution-verifications/{token}/confirm" in paths
    assert "/api/v1/public/institution-verifications/{token}/report-discrepancy" in paths
    assert "/api/v1/public/institution-verifications/{token}/request-clarification" in paths


@pytest.mark.asyncio
async def test_public_projection_does_not_touch_lazy_request_organization() -> None:
    service = PublicInstitutionVerificationService.__new__(PublicInstitutionVerificationService)
    request = _LazyOrganizationRequest()
    education = SimpleNamespace(
        institution_name="Kairo University",
        degree="BSc",
        field_of_study="Computer Science",
        start_date=datetime(2020, 1, 1, tzinfo=UTC),
        end_date=datetime(2024, 1, 1, tzinfo=UTC),
    )
    evidence_item = SimpleNamespace()
    evidence_response = SimpleNamespace(
        public_id=uuid4(),
        original_filename="transcript.pdf",
        field_key="education_evidence",
        document_type="transcript",
        evidence_type="transcript",
        created_at=datetime.now(tz=UTC),
        download_url="https://example.test/evidence.pdf",
    )
    service._education = SimpleNamespace(get_active_by_id=AsyncMock(return_value=education))
    service._evidence = SimpleNamespace(list_for_request=AsyncMock(return_value=[evidence_item]))
    service._verification_service = SimpleNamespace(
        _filter_evidence_by_consent=lambda _request, items: items,
        _to_evidence_response=AsyncMock(return_value=evidence_response),
    )

    result = await service._build_request_projection(request)

    assert result.requested_by == "Institution Acceptance University"
    assert result.candidate.programme == "Computer Science"
    assert result.evidence[0].name == "transcript.pdf"


@pytest.mark.asyncio
async def test_public_projection_accepts_string_request_type() -> None:
    service = PublicInstitutionVerificationService.__new__(PublicInstitutionVerificationService)
    request = SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        education_id=uuid4(),
        target_organization_name="Institution Acceptance University",
        subject_name="Synthetic Student",
        request_type="education",
        created_at=datetime.now(tz=UTC),
        consented_at=datetime.now(tz=UTC),
        candidate_response="Candidate supplied note",
    )
    education = SimpleNamespace(
        institution_name="Kairo University",
        degree="BSc",
        field_of_study="Computer Science",
        start_date=datetime(2020, 1, 1, tzinfo=UTC),
        end_date=datetime(2024, 1, 1, tzinfo=UTC),
    )
    evidence_item = SimpleNamespace()
    evidence_response = SimpleNamespace(
        public_id=uuid4(),
        original_filename="transcript.pdf",
        field_key="education_evidence",
        document_type="transcript",
        evidence_type="transcript",
        created_at=datetime.now(tz=UTC),
        download_url="https://example.test/evidence.pdf",
    )
    service._education = SimpleNamespace(get_active_by_id=AsyncMock(return_value=education))
    service._evidence = SimpleNamespace(list_for_request=AsyncMock(return_value=[evidence_item]))
    service._verification_service = SimpleNamespace(
        _filter_evidence_by_consent=lambda _request, items: items,
        _to_evidence_response=AsyncMock(return_value=evidence_response),
    )

    result = await service._build_request_projection(request)

    assert result.purpose == "Education verification request"
    assert result.requested_by == "Institution Acceptance University"


def test_review_link_uses_configured_institution_portal_origin() -> None:
    service = PublicInstitutionVerificationService.__new__(PublicInstitutionVerificationService)
    service._settings = SimpleNamespace(  # noqa: SLF001
        institution_portal_base_url="https://institution-staging.example.com/",
        app_public_base_url="https://candidate.example.com",
    )

    link = service._review_link("public-token-value")

    assert link == "https://institution-staging.example.com/institution/verify/public-token-value"
    assert "candidate.example.com" not in link


def test_review_link_requires_dedicated_institution_portal_origin() -> None:
    service = PublicInstitutionVerificationService.__new__(PublicInstitutionVerificationService)
    service._settings = SimpleNamespace(  # noqa: SLF001
        institution_portal_base_url=None,
        app_public_base_url="https://d3kpvsn9kfajzc.cloudfront.net",
    )

    with pytest.raises(
        ValidationAppError,
        match="INSTITUTION_PORTAL_BASE_URL",
    ):
        service._review_link("public-token-value")


@pytest.mark.asyncio
async def test_confirm_public_response_advances_to_admin_quality_review_once() -> None:
    service = PublicInstitutionVerificationService.__new__(PublicInstitutionVerificationService)
    now = datetime.now(tz=UTC)
    request = SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        education_id=uuid4(),
        request_type=VerificationRequestType.EDUCATION,
        subject_name="Synthetic Student",
        status=VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE,
        target_organization_name="Institution Acceptance University",
    )
    row = SimpleNamespace(
        public_id=uuid4(),
        verification_request_id=request.id,
        revoked_at=None,
        expires_at=now + timedelta(hours=4),
        responded_at=None,
        response_action="pending",
        response_note=None,
        response_metadata={},
    )
    service._load_by_token = AsyncMock(return_value=row)
    service._requests = SimpleNamespace(get_by_id=AsyncMock(return_value=request))
    service._workflow = SimpleNamespace(transition=AsyncMock())
    service._notifications = SimpleNamespace(create_and_dispatch_for_admin_roles=AsyncMock())
    service._session = SimpleNamespace(commit=AsyncMock())
    service.get_public_request = AsyncMock(
        return_value=PublicInstitutionVerificationReadResponse(
            token="valid-token-value",
            state="completed",
        )
    )

    result = await service.confirm_from_public(
        "valid-token-value",
        PublicInstitutionVerificationConfirmRequest(note="Records match"),
    )

    assert result.state == "completed"
    assert row.responded_at is not None
    assert row.response_action == "confirm"
    assert row.response_note == "Records match"
    assert service._workflow.transition.await_count == 2
    statuses = [
        call.kwargs["target_status"]
        for call in service._workflow.transition.await_args_list
    ]
    assert statuses == [
        VerificationRequestStatus.IN_PROGRESS,
        VerificationRequestStatus.PENDING_ADMIN_QUALITY_REVIEW,
    ]
    service._notifications.create_and_dispatch_for_admin_roles.assert_awaited_once()
    service._session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_identical_repeat_response_is_idempotent() -> None:
    service = PublicInstitutionVerificationService.__new__(PublicInstitutionVerificationService)
    now = datetime.now(tz=UTC)
    request = SimpleNamespace(
        id=uuid4(),
        status=VerificationRequestStatus.PENDING_ADMIN_QUALITY_REVIEW,
    )
    row = SimpleNamespace(
        verification_request_id=request.id,
        revoked_at=None,
        expires_at=now + timedelta(hours=1),
        responded_at=now,
        response_action="confirm",
        response_metadata={"note": "Records match"},
    )
    expected = PublicInstitutionVerificationReadResponse(
        token="valid-token-value",
        state="completed",
    )
    service._load_by_token = AsyncMock(return_value=row)
    service._requests = SimpleNamespace(get_by_id=AsyncMock(return_value=request))
    service.get_public_request = AsyncMock(return_value=expected)

    result = await service.confirm_from_public(
        "valid-token-value",
        PublicInstitutionVerificationConfirmRequest(note="Records match"),
    )

    assert result == expected
    service.get_public_request.assert_awaited_once_with("valid-token-value")


@pytest.mark.asyncio
async def test_conflicting_repeat_response_fails_closed() -> None:
    service = PublicInstitutionVerificationService.__new__(PublicInstitutionVerificationService)
    now = datetime.now(tz=UTC)
    request = SimpleNamespace(
        id=uuid4(),
        status=VerificationRequestStatus.PENDING_ADMIN_QUALITY_REVIEW,
    )
    row = SimpleNamespace(
        verification_request_id=request.id,
        revoked_at=None,
        expires_at=now + timedelta(hours=1),
        responded_at=now,
        response_action="confirm",
        response_metadata={"note": "Records match"},
    )
    service._load_by_token = AsyncMock(return_value=row)
    service._requests = SimpleNamespace(get_by_id=AsyncMock(return_value=request))

    with pytest.raises(ConflictError, match="already been used"):
        await service.request_clarification_from_public(
            "valid-token-value",
            PublicInstitutionVerificationClarificationRequest(
                fields=["student_id"],
                message="Need another identifier",
                request_document=False,
            ),
        )
