"""Canonical employment verification workflow security and contract tests."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.v1.router import api_router
from app.employment.enums import DocumentVerificationStatus
from app.exceptions import ConflictError, EmploymentWorkflowError
from app.schemas.verification_request import VerificationContactRequest
from app.services.employer_verification_service import EmployerVerificationService
from app.services.verification_request_service import VerificationRequestService
from app.verification_requests.enums import (
    VerificationContactType,
    VerificationRequestStatus,
    VerificationRequestType,
)


def test_candidate_employer_email_route_is_not_registered() -> None:
    paths: set[str] = set()
    for included in api_router.routes:
        router = getattr(included, "original_router", None)
        if router is not None:
            paths.update(route.path for route in router.routes if hasattr(route, "path"))

    assert "/employments/{employment_id}/employer-verification/request" not in paths
    assert "/employments/{employment_id}/verification-request" in paths


def test_verification_contact_requires_valid_email_and_type() -> None:
    contact = VerificationContactRequest(
        contact_email="hr@company.example",
        contact_type=VerificationContactType.HR,
    )

    assert str(contact.contact_email) == "hr@company.example"
    assert contact.contact_type == VerificationContactType.HR


@pytest.mark.asyncio
async def test_employment_evidence_requires_completed_owned_document() -> None:
    service = VerificationRequestService.__new__(VerificationRequestService)
    actor_id = uuid4()
    employment_id = uuid4()
    document_id = uuid4()
    request = SimpleNamespace(id=uuid4(), employment_id=employment_id)
    document = SimpleNamespace(
        id=document_id,
        uploaded_by_user_id=actor_id,
        verification_status=DocumentVerificationStatus.PENDING_UPLOAD.value,
    )

    class Documents:
        async def get_active_for_employment(self, candidate_employment_id, candidate_document_id):
            assert candidate_employment_id == employment_id
            assert candidate_document_id == document_id
            return document

    class Evidence:
        async def get_by_employment_document(self, request_id, candidate_document_id):
            return None

    service._employment_documents = Documents()
    service._evidence = Evidence()

    with pytest.raises(ConflictError, match="upload is not complete"):
        await service._validate_employment_document_evidence(request, actor_id, document_id)


@pytest.mark.asyncio
async def test_candidate_submission_only_enters_admin_review() -> None:
    service = VerificationRequestService.__new__(VerificationRequestService)
    actor_id = uuid4()
    request = SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        employment_id=uuid4(),
        request_type=VerificationRequestType.EMPLOYMENT,
        status=VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION,
        submitted_for_admin_review_at=None,
        organization_outreach_sent_at=None,
    )
    evidence = SimpleNamespace(employment_document_id=uuid4())
    transitions: list[tuple[VerificationRequestStatus, str]] = []

    async def require_subject(*_args):
        return request

    async def commit_and_reload(_public_id):
        return request

    class EvidenceRepository:
        async def list_for_request(self, _request_id):
            return [evidence]

    class ContactRepository:
        async def get_current(self, _request_id):
            return SimpleNamespace(public_id=uuid4())

    class Workflow:
        async def transition(self, target, *, target_status, event_type, **_kwargs):
            transitions.append((target_status, event_type))
            target.status = target_status

    service._require_subject_request = require_subject
    service._commit_and_reload = commit_and_reload
    service._evidence = EvidenceRepository()
    service._contacts = ContactRepository()
    service._workflow = Workflow()

    result = await service.submit_for_review(actor_id, "candidate@example.com", request.public_id)

    assert result.status == VerificationRequestStatus.PENDING_ADMIN_REVIEW
    assert transitions == [(VerificationRequestStatus.PENDING_ADMIN_REVIEW, "verification_submitted")]
    assert request.organization_outreach_sent_at is None


@pytest.mark.asyncio
async def test_employer_outreach_fails_before_admin_approval() -> None:
    service = EmployerVerificationService.__new__(EmployerVerificationService)
    request = SimpleNamespace(
        employment_id=uuid4(),
        status=VerificationRequestStatus.PENDING_ADMIN_REVIEW,
    )

    with pytest.raises(EmploymentWorkflowError, match="requires Admin approval"):
        await service.initiate_admin_outreach(
            actor_user_id=uuid4(),
            verification_request=request,
            payload=SimpleNamespace(),
        )
