"""Focused tests for the HR workspace verification request contract."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.organization import Organization
from app.models.verification_request import VerificationRequest
from app.models.verification_request_evidence import VerificationRequestEvidence
from app.organization.enums import OrganizationType, OrganizationVerificationState
from app.schemas.verification_request import (
    VerificationRequestAssignReviewerRequest,
    VerificationRequestEvidenceResponse,
)
from app.services.verification_request_service import VerificationRequestService
from app.verification_requests.enums import VerificationRequestStatus, VerificationRequestType


def _build_service() -> VerificationRequestService:
    service = VerificationRequestService.__new__(VerificationRequestService)
    service._settings = SimpleNamespace(s3_documents_bucket="documents-bucket")
    service._evidence = SimpleNamespace(list_for_request=AsyncMock(return_value=[]))
    service._employments = SimpleNamespace(get_active_by_id=AsyncMock(return_value=None))
    service._users = SimpleNamespace(get_by_id=AsyncMock(return_value=None))
    service._employment_documents = SimpleNamespace(get_active_by_id=AsyncMock(return_value=None))
    service._user_documents = SimpleNamespace(get_active_by_id=AsyncMock(return_value=None))
    return service


def _build_request() -> VerificationRequest:
    request = VerificationRequest(
        organization_id=uuid4(),
        subject_name="Candidate One",
        subject_email="candidate@example.com",
        target_organization_name="Kairo HR",
        target_organization_email="hr@kairo.example.com",
        request_type=VerificationRequestType.EMPLOYMENT,
        status=VerificationRequestStatus.ACCEPTED,
        requested_by_user_id=uuid4(),
        trust_context={"source": "workspace"},
        target_organization_metadata={"channel": "hr_workspace"},
    )
    request.id = uuid4()
    request.public_id = uuid4()
    request.created_at = datetime.now(tz=UTC)
    request.updated_at = request.created_at
    request.consented_fields = [
        "employment.role",
        "employment.date_range",
        "employment.employer_name",
    ]
    request.consented_evidence_scope = ["employment.start_date"]
    request.organization_internal_note = "Private to the responding HR team."
    request.assigned_to_user_id = uuid4()
    request.organization = Organization(
        created_by_user_id=uuid4(),
        name="Northstar Technologies",
        organization_type=OrganizationType.EMPLOYER,
        verification_state=OrganizationVerificationState.VERIFIED,
    )
    request.organization.public_id = uuid4()
    request.organization.suspended_at = None
    return request


@pytest.mark.asyncio
async def test_subject_projection_hides_org_private_fields() -> None:
    service = _build_service()
    request = _build_request()

    response = await service._to_subject_response(request)  # type: ignore[attr-defined]

    assert response.organization_internal_note is None
    assert response.assigned_reviewer is None
    assert response.review_status is None
    assert response.is_assigned_to_current_user is None
    assert response.verification_target is not None
    assert response.verification_target.metadata["channel"] == "hr_workspace"


@pytest.mark.asyncio
async def test_org_projection_exposes_reviewer_and_internal_note() -> None:
    service = _build_service()
    request = _build_request()
    request.employment_id = uuid4()
    viewer_user_id = request.assigned_to_user_id
    service._users.get_by_id = AsyncMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(
            id=request.assigned_to_user_id,
            full_name="Rhea Kapoor",
            email="rhea@kairo.example.com",
            role="member",
        )
    )
    service._evidence.list_for_request = AsyncMock(  # type: ignore[method-assign]
        return_value=[
            SimpleNamespace(
                evidence_type="employment_detail",
                field_key="employment.start_date",
                document_id=None,
                employment_document_id=uuid4(),
            )
        ]
    )
    service._employments.get_active_by_id = AsyncMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(
            employer_legal_name="Northstar Technologies",
            job_title="Senior Product Engineer",
            start_date=date(2021, 3, 14),
            end_date=date(2024, 8, 30),
            employment_type="full_time",
            work_location_country="IN",
            work_location_region="KA",
        )
    )

    response = await service._to_org_response(request, viewer_user_id)  # type: ignore[attr-defined]

    assert response.organization_internal_note == "Private to the responding HR team."
    assert response.assigned_reviewer is not None
    assert response.assigned_reviewer.email == "rhea@kairo.example.com"
    assert response.review_status == "assigned"
    assert response.is_assigned_to_current_user is True
    assert response.employment_claim is not None
    assert response.employment_claim.role == "Senior Product Engineer"
    assert response.evidence_summary.total_items == 1


@pytest.mark.asyncio
async def test_org_evidence_projection_includes_download_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service()
    evidence = VerificationRequestEvidence(
        verification_request_id=uuid4(),
        submitted_by_user_id=uuid4(),
        evidence_type="employment_letter",
        field_key="employment_evidence",
        employment_document_id=uuid4(),
        status="submitted",
    )
    evidence.public_id = uuid4()
    evidence.created_at = datetime.now(tz=UTC)
    evidence.updated_at = evidence.created_at
    service._employment_documents.get_active_by_id = AsyncMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(
            document_type="employment_letter",
            original_filename="employment-letter.pdf",
            content_type="application/pdf",
            byte_size=24576,
            verification_status="uploaded",
            object_key="employment-documents/test.pdf",
        )
    )

    presign = AsyncMock(return_value="https://example.test/download")
    monkeypatch.setattr(
        "app.services.verification_request_service.generate_presigned_get_url",
        presign,
    )

    response: VerificationRequestEvidenceResponse = await service._to_evidence_response(  # type: ignore[attr-defined]
        evidence,
        include_download_url=True,
    )

    assert response.document_type == "employment_letter"
    assert response.original_filename == "employment-letter.pdf"
    assert response.download_url == "https://example.test/download"
    assert response.download_url_expires_in_seconds == 300
    presign.assert_awaited_once()


@pytest.mark.asyncio
async def test_assign_reviewer_resolves_membership_public_id_to_user_assignment() -> None:
    service = _build_service()
    request = _build_request()
    actor_user_id = uuid4()
    member_public_id = uuid4()
    assignee_user_id = uuid4()
    assignee = SimpleNamespace(
        id=assignee_user_id,
        email="rhea@kairo.example.com",
        full_name="Rhea Kapoor",
    )

    service._organizations = SimpleNamespace(  # type: ignore[attr-defined]
        get_member_by_public_id=AsyncMock(
            return_value=SimpleNamespace(
                public_id=member_public_id,
                user_id=assignee_user_id,
                suspended_at=None,
                user=assignee,
            )
        ),
        get_membership=AsyncMock(),
    )
    service._workflow = SimpleNamespace(record_action=AsyncMock())  # type: ignore[attr-defined]
    service._require_manageable_request = AsyncMock(return_value=request)  # type: ignore[attr-defined]
    service._commit_reload_org_response = AsyncMock(return_value=SimpleNamespace(ok=True))  # type: ignore[attr-defined]

    result = await service.assign_reviewer(
        actor_user_id,
        request.public_id,
        VerificationRequestAssignReviewerRequest(
            organization_member_public_id=member_public_id,
        ),
    )

    assert request.assigned_to_user_id == assignee_user_id
    assert result.ok is True
    service._organizations.get_member_by_public_id.assert_awaited_once_with(  # type: ignore[attr-defined]
        request.organization_id,
        member_public_id,
    )
    service._organizations.get_membership.assert_not_called()  # type: ignore[attr-defined]
    service._workflow.record_action.assert_awaited_once()  # type: ignore[attr-defined]
