"""Canonical employment verification workflow security and contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.api.v1.router import api_router
from app.education.enums import EducationVerificationStatus
from app.employment.enums import DocumentVerificationStatus
from app.exceptions import ConflictError, EmploymentWorkflowError, ForbiddenError, NotFoundError
from app.notifications.contracts import NotificationRequest
from app.organization.enums import OrganizationRole
from app.schemas.verification_request import (
    EducationVerificationDraftRequest,
    VerificationContactRequest,
    VerificationRequestSubmitForReviewRequest,
)
from app.services.employer_verification_service import EmployerVerificationService
from app.services.verification_request_service import VerificationRequestService
from app.verification_requests.enums import (
    VerificationContactType,
    VerificationRequestEventSource,
    VerificationRequestOriginType,
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


def test_candidate_education_verification_routes_are_registered() -> None:
    paths: set[str] = set()
    for included in api_router.routes:
        router = getattr(included, "original_router", None)
        if router is not None:
            paths.update(route.path for route in router.routes if hasattr(route, "path"))

    assert "/educations/{education_id}/verification-request" in paths


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
async def test_education_evidence_requires_completed_owned_document() -> None:
    service = VerificationRequestService.__new__(VerificationRequestService)
    actor_id = uuid4()
    education_id = uuid4()
    document_id = uuid4()
    request = SimpleNamespace(id=uuid4(), education_id=education_id)
    document = SimpleNamespace(
        id=document_id,
        uploaded_by_user_id=actor_id,
        checksum_sha256=None,
    )

    class Documents:
        async def get_for_education(self, candidate_document_id, candidate_education_id):
            assert candidate_document_id == document_id
            assert candidate_education_id == education_id
            return document

    class Evidence:
        async def get_by_education_document(self, request_id, candidate_document_id):
            return None

    service._education_documents = Documents()
    service._evidence = Evidence()

    with pytest.raises(ConflictError, match="upload is not complete"):
        await service._validate_education_document_evidence(request, actor_id, document_id)


@pytest.mark.asyncio
async def test_education_draft_links_completed_owned_evidence() -> None:
    service = VerificationRequestService.__new__(VerificationRequestService)
    actor_id = uuid4()
    education_id = uuid4()
    document_id = uuid4()
    request = SimpleNamespace(id=uuid4(), public_id=uuid4())
    education = SimpleNamespace(
        id=education_id,
        institution_name="Kairo University",
        verification_status=EducationVerificationStatus.DRAFT.value,
    )
    document = SimpleNamespace(id=document_id, document_type="transcript")
    evidence_items = []

    class Educations:
        async def get_owned(self, candidate_education_id, candidate_user_id):
            assert candidate_education_id == education_id
            assert candidate_user_id == actor_id
            return education

    class Requests:
        async def get_active_for_education(self, candidate_education_id):
            assert candidate_education_id == education_id
            return None

        async def create(self, candidate_request):
            assert candidate_request.education_id == education_id
            assert candidate_request.request_type == VerificationRequestType.EDUCATION
            return request

    class Contacts:
        async def create(self, _contact):
            return SimpleNamespace(public_id=uuid4())

    class Documents:
        async def get_for_education(self, candidate_document_id, candidate_education_id):
            assert candidate_document_id == document_id
            assert candidate_education_id == education_id
            return document

    class Evidence:
        async def create(self, evidence):
            evidence_items.append(evidence)
            evidence.public_id = uuid4()
            return evidence

    class Workflow:
        async def record_action(self, *_args, **_kwargs):
            return None

    class People:
        async def resolve_for_verification_request(self, *_args, **_kwargs):
            return None

    async def subject(_actor_id):
        return SimpleNamespace(email="candidate@example.com", full_name="Candidate")

    async def validate(_request, _actor_id, candidate_document_id, **_kwargs):
        assert candidate_document_id == document_id

    async def response(_public_id):
        return request

    service._educations = Educations()
    service._requests = Requests()
    service._contacts = Contacts()
    service._education_documents = Documents()
    service._evidence = Evidence()
    service._workflow = Workflow()
    service._people = People()
    service._require_subject_user = subject
    service._validate_education_document_evidence = validate
    service._commit_reload_subject_response = response

    payload = EducationVerificationDraftRequest(
        verification_contact=VerificationContactRequest(
            contact_email="registrar@kairo.example",
            contact_type="authorized_representative",
        ),
        education_document_ids=[document_id],
    )
    result = await service.create_education_verification_draft(actor_id, education_id, payload)

    assert result is request
    assert education.verification_status == EducationVerificationStatus.PENDING.value
    assert len(evidence_items) == 1
    assert evidence_items[0].education_document_id == document_id


@pytest.mark.asyncio
async def test_candidate_submission_only_enters_admin_review() -> None:
    service = VerificationRequestService.__new__(VerificationRequestService)
    actor_id = uuid4()
    admin_role_calls: list[NotificationRequest] = []
    request = SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        employment_id=uuid4(),
        organization=None,
        target_organization_name=None,
        subject_name="Candidate One",
        request_type=VerificationRequestType.EMPLOYMENT,
        status=VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION,
        submitted_for_admin_review_at=None,
        organization_outreach_sent_at=None,
        consented_fields=[],
        consented_evidence_scope=[],
        consented_at=None,
        consent_version=None,
    )
    evidence = SimpleNamespace(employment_document_id=uuid4())
    transitions: list[tuple[VerificationRequestStatus, str]] = []

    async def require_subject(*_args):
        return request

    async def commit_reload_subject_response(_public_id):
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

    class Notifications:
        async def create_and_dispatch_for_admin_roles(self, notification: NotificationRequest):
            admin_role_calls.append(notification)

    service._require_subject_request = require_subject
    service._commit_reload_subject_response = commit_reload_subject_response
    service._evidence = EvidenceRepository()
    service._contacts = ContactRepository()
    service._workflow = Workflow()
    service._notifications = Notifications()

    result = await service.submit_for_review(
        actor_id,
        "candidate@example.com",
        request.public_id,
        VerificationRequestSubmitForReviewRequest(
            consented_fields=["employment.role", "employment_dates"],
            consented_evidence_scope=["employment_letter"],
            consent_version="v1",
        ),
    )

    assert result.status == VerificationRequestStatus.PENDING_ADMIN_REVIEW
    assert transitions == [(VerificationRequestStatus.PENDING_ADMIN_REVIEW, "verification_submitted")]
    assert request.organization_outreach_sent_at is None
    assert request.consented_fields == ["employment.role", "employment_dates"]
    assert request.consented_evidence_scope == ["employment_letter"]
    assert request.consented_at is not None
    assert request.consent_version == "v1"
    assert [call.event_type for call in admin_role_calls] == ["admin_verification_review_required"]


@pytest.mark.asyncio
async def test_education_candidate_submission_requires_education_evidence() -> None:
    service = VerificationRequestService.__new__(VerificationRequestService)
    actor_id = uuid4()
    admin_role_calls: list[NotificationRequest] = []
    request = SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        employment_id=None,
        education_id=uuid4(),
        organization=None,
        target_organization_name=None,
        subject_name="Candidate One",
        request_type=VerificationRequestType.EDUCATION,
        status=VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION,
        submitted_for_admin_review_at=None,
        consented_fields=[],
        consented_evidence_scope=[],
        consented_at=None,
        consent_version=None,
    )

    async def require_subject(*_args):
        return request

    class EvidenceRepository:
        async def list_for_request(self, _request_id):
            return [SimpleNamespace(education_document_id=uuid4())]

    class ContactRepository:
        async def get_current(self, _request_id):
            return SimpleNamespace(public_id=uuid4())

    class Workflow:
        async def transition(self, target, *, target_status, **_kwargs):
            target.status = target_status

    class Notifications:
        async def create_and_dispatch_for_admin_roles(self, notification: NotificationRequest):
            admin_role_calls.append(notification)

    async def commit_reload_subject_response(_public_id):
        return request

    service._require_subject_request = require_subject
    service._evidence = EvidenceRepository()
    service._contacts = ContactRepository()
    service._workflow = Workflow()
    service._commit_reload_subject_response = commit_reload_subject_response
    service._notifications = Notifications()

    result = await service.submit_for_review(
        actor_id,
        "candidate@example.com",
        request.public_id,
        VerificationRequestSubmitForReviewRequest(
            consented_fields=["education.degree", "education_dates"],
            consented_evidence_scope=["transcript"],
            consent_version="v1",
        ),
    )

    assert result.status == VerificationRequestStatus.PENDING_ADMIN_REVIEW
    assert [call.event_type for call in admin_role_calls] == ["admin_verification_review_required"]
    assert request.consented_fields == ["education.degree", "education_dates"]
    assert request.consented_evidence_scope == ["transcript"]
    assert request.consented_at is not None
    assert request.consent_version == "v1"


@pytest.mark.asyncio
async def test_get_employment_verification_request_returns_latest_terminal_request_for_owner() -> None:
    service = VerificationRequestService.__new__(VerificationRequestService)
    actor_id = uuid4()
    claim_employment_id = uuid4()
    request = SimpleNamespace(public_id=uuid4(), status=VerificationRequestStatus.VERIFIED)

    class Employments:
        async def get_owned_active(self, candidate_employment_id, candidate_user_id):
            assert candidate_employment_id == claim_employment_id
            assert candidate_user_id == actor_id
            return SimpleNamespace(id=claim_employment_id)

    class Requests:
        async def get_latest_for_subject_employment(self, *, employment_id: UUID, subject_user_id: UUID):
            assert employment_id == claim_employment_id
            assert subject_user_id == actor_id
            return request

    async def response(_request):
        return _request

    service._employments = Employments()
    service._requests = Requests()
    service._to_subject_response = response

    result = await service.get_employment_verification_request(actor_id, claim_employment_id)

    assert result is request


@pytest.mark.asyncio
async def test_get_education_verification_request_returns_latest_terminal_request_for_owner() -> None:
    service = VerificationRequestService.__new__(VerificationRequestService)
    actor_id = uuid4()
    claim_education_id = uuid4()
    request = SimpleNamespace(public_id=uuid4(), status=VerificationRequestStatus.VERIFIED)

    class Educations:
        async def get_owned(self, candidate_education_id, candidate_user_id):
            assert candidate_education_id == claim_education_id
            assert candidate_user_id == actor_id
            return SimpleNamespace(id=claim_education_id)

    class Requests:
        async def get_latest_for_subject_education(self, *, education_id: UUID, subject_user_id: UUID):
            assert education_id == claim_education_id
            assert subject_user_id == actor_id
            return request

    async def response(_request):
        return _request

    service._educations = Educations()
    service._requests = Requests()
    service._to_subject_response = response

    result = await service.get_education_verification_request(actor_id, claim_education_id)

    assert result is request


@pytest.mark.asyncio
async def test_org_projection_only_exposes_consented_claim_fields_and_evidence() -> None:
    service = VerificationRequestService.__new__(VerificationRequestService)
    subject_id = uuid4()
    actor_id = uuid4()
    request = SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        employment_id=uuid4(),
        education_id=None,
        origin_type=VerificationRequestOriginType.SUBJECT_INITIATED,
        organization_id=uuid4(),
        organization=SimpleNamespace(
            public_id=uuid4(),
            name="Acme Corp",
            organization_type="employer",
            verification_state="verified",
            suspended_at=None,
        ),
        trust_invitation=None,
        subject_name="Candidate",
        subject_email="candidate@example.com",
        target_organization_name="Acme Corp",
        target_organization_email="hr@acme.com",
        request_type=VerificationRequestType.EMPLOYMENT,
        status=VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE,
        priority="normal",
        due_date=None,
        trust_context={},
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
        accepted_at=None,
        consented_at=datetime.now(tz=UTC),
        consent_version="v1",
        consented_fields=["employment_dates"],
        consented_evidence_scope=["employment_letter"],
        candidate_response=None,
        candidate_response_submitted_at=None,
        target_organization_metadata={},
        assigned_to_user_id=None,
        organization_internal_note=None,
        subject_user_id=subject_id,
    )
    employment = SimpleNamespace(
        employer_legal_name="Acme Corp",
        job_title="Engineer",
        start_date=datetime(2024, 1, 1, tzinfo=UTC).date(),
        end_date=datetime(2025, 1, 1, tzinfo=UTC).date(),
        employment_type="full_time",
        work_location_country="IN",
        work_location_region="KA",
    )
    service._evidence = SimpleNamespace(
        list_for_request=AsyncMock(
            return_value=[
                SimpleNamespace(
                    evidence_type="employment_letter",
                    field_key="employment_evidence",
                    document_id=None,
                    employment_document_id=uuid4(),
                    education_document_id=None,
                ),
                SimpleNamespace(
                    evidence_type="paystub",
                    field_key="employment_paystub",
                    document_id=None,
                    employment_document_id=uuid4(),
                    education_document_id=None,
                ),
            ]
        )
    )
    service._employments = SimpleNamespace(get_active_by_id=AsyncMock(return_value=employment))
    service._educations = SimpleNamespace(get_active_by_id=AsyncMock(return_value=None))
    service._users = SimpleNamespace(get_by_id=AsyncMock(return_value=None))

    response = await service._to_org_response(request, actor_id)

    assert response.employment_claim is not None
    assert response.employment_claim.start_date == employment.start_date
    assert response.employment_claim.end_date == employment.end_date
    assert response.employment_claim.employer_name is None
    assert response.employment_claim.role is None
    assert response.evidence_summary.total_items == 1
    assert response.evidence_summary.field_keys == ["employment_evidence"]


@pytest.mark.asyncio
async def test_employer_outreach_fails_before_admin_approval() -> None:
    service = EmployerVerificationService.__new__(EmployerVerificationService)
    request = SimpleNamespace(
        employment_id=uuid4(),
        status=VerificationRequestStatus.PENDING_ADMIN_REVIEW,
        approved_for_organization_verification_at=None,
    )

    with pytest.raises(EmploymentWorkflowError, match="requires Admin approval"):
        await service.initiate_admin_outreach(
            actor_user_id=uuid4(),
            verification_request=request,
            payload=SimpleNamespace(),
        )


@pytest.mark.asyncio
async def test_employer_outreach_allows_admin_approved_request_after_organization_resolution() -> None:
    service = EmployerVerificationService.__new__(EmployerVerificationService)
    service.request_verification = AsyncMock(
        return_value=SimpleNamespace(verifier_email_masked="h***@example.com")
    )
    service._workflow = SimpleNamespace(record_action=AsyncMock())
    service._session = SimpleNamespace(commit=AsyncMock())
    request = SimpleNamespace(
        id=uuid4(),
        employment_id=uuid4(),
        subject_user_id=uuid4(),
        status=VerificationRequestStatus.PENDING_ORGANIZATION_RESOLUTION,
        approved_for_organization_verification_at=datetime.now(tz=UTC),
    )

    await service.initiate_admin_outreach(
        actor_user_id=uuid4(),
        verification_request=request,
        payload=SimpleNamespace(),
    )

    service.request_verification.assert_awaited_once()
    service._workflow.record_action.assert_awaited_once()
    service._session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_target_hr_member_can_accept_pending_organization_acceptance() -> None:
    service = VerificationRequestService.__new__(VerificationRequestService)
    actor_id = uuid4()
    organization_id = uuid4()
    organization_public_id = uuid4()
    request = SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        organization_id=organization_id,
        organization=SimpleNamespace(public_id=organization_public_id, suspended_at=None),
        subject_user_id=uuid4(),
        subject_email="candidate@example.com",
        status=VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE,
        employment_id=uuid4(),
    )
    membership = SimpleNamespace(
        public_id=uuid4(),
        role=OrganizationRole.OWNER.value,
        suspended_at=None,
    )
    transitions: list[
        tuple[
            VerificationRequestStatus,
            str,
            VerificationRequestEventSource,
            dict[str, object],
        ]
    ] = []

    async def get_required_request(_public_id):
        return request

    async def get_membership_for_request(_request, _actor_id):
        return membership

    class Workflow:
        async def transition(
            self,
            target,
            *,
            target_status,
            event_type,
            event_source,
            metadata,
            **_kwargs,
        ):
            transitions.append((target_status, event_type, event_source, metadata))
            target.status = target_status

    async def commit_reload_org_response(_public_id, _actor_user_id):
        return request

    bind = VerificationRequestService

    service._get_required_request = get_required_request
    service._get_membership_for_request = get_membership_for_request
    service._workflow = Workflow()
    service._commit_reload_org_response = commit_reload_org_response
    service._assert_active_membership_access = bind._assert_active_membership_access.__get__(service, bind)
    service._is_subject_actor = bind._is_subject_actor.__get__(service, bind)

    result = await service.accept(actor_id, "hr@example.com", request.public_id)

    assert result is request
    assert request.status == VerificationRequestStatus.IN_PROGRESS
    assert transitions == [
        (
            VerificationRequestStatus.IN_PROGRESS,
            "verification_request_organization_accepted",
            VerificationRequestEventSource.ORGANIZATION,
            {
                "organization_member_public_id": str(membership.public_id),
                "organization_role": OrganizationRole.OWNER.value,
            },
        )
    ]


@pytest.mark.asyncio
async def test_subject_cannot_accept_pending_organization_acceptance() -> None:
    service = VerificationRequestService.__new__(VerificationRequestService)
    actor_id = uuid4()
    request = SimpleNamespace(
        public_id=uuid4(),
        organization_id=uuid4(),
        organization=SimpleNamespace(suspended_at=None),
        subject_user_id=actor_id,
        subject_email="candidate@example.com",
        status=VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE,
    )

    async def get_required_request(_public_id):
        return request

    async def get_membership_for_request(_request, _actor_id):
        return None

    bind = VerificationRequestService
    service._get_required_request = get_required_request
    service._get_membership_for_request = get_membership_for_request
    service._is_subject_actor = bind._is_subject_actor.__get__(service, bind)

    with pytest.raises(
        ForbiddenError,
        match="Only the target organization can accept this verification request",
    ):
        await service.accept(actor_id, "candidate@example.com", request.public_id)


@pytest.mark.asyncio
async def test_unrelated_organization_cannot_accept_request() -> None:
    service = VerificationRequestService.__new__(VerificationRequestService)
    request = SimpleNamespace(
        public_id=uuid4(),
        organization_id=uuid4(),
        organization=SimpleNamespace(suspended_at=None),
        subject_user_id=uuid4(),
        subject_email="candidate@example.com",
        status=VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE,
    )

    async def get_required_request(_public_id):
        return request

    async def get_membership_for_request(_request, _actor_id):
        return None

    bind = VerificationRequestService
    service._get_required_request = get_required_request
    service._get_membership_for_request = get_membership_for_request
    service._is_subject_actor = bind._is_subject_actor.__get__(service, bind)

    with pytest.raises(NotFoundError, match="Verification request not found"):
        await service.accept(uuid4(), "hr@example.com", request.public_id)


@pytest.mark.asyncio
async def test_suspended_membership_is_rejected_for_organization_acceptance() -> None:
    service = VerificationRequestService.__new__(VerificationRequestService)
    request = SimpleNamespace(
        public_id=uuid4(),
        organization_id=uuid4(),
        organization=SimpleNamespace(suspended_at=None),
        subject_user_id=uuid4(),
        subject_email="candidate@example.com",
        status=VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE,
    )
    membership = SimpleNamespace(
        public_id=uuid4(),
        role=OrganizationRole.REVIEWER,
        suspended_at=datetime.now(tz=UTC),
    )

    async def get_required_request(_public_id):
        return request

    async def get_membership_for_request(_request, _actor_id):
        return membership

    bind = VerificationRequestService
    service._get_required_request = get_required_request
    service._get_membership_for_request = get_membership_for_request
    service._assert_active_membership_access = bind._assert_active_membership_access.__get__(service, bind)
    service._is_subject_actor = bind._is_subject_actor.__get__(service, bind)

    with pytest.raises(ForbiddenError, match="Organization membership is suspended"):
        await service.accept(uuid4(), "hr@example.com", request.public_id)


@pytest.mark.asyncio
async def test_wrong_state_is_rejected_for_organization_acceptance() -> None:
    service = VerificationRequestService.__new__(VerificationRequestService)
    request = SimpleNamespace(
        public_id=uuid4(),
        organization_id=uuid4(),
        organization=SimpleNamespace(suspended_at=None),
        subject_user_id=uuid4(),
        subject_email="candidate@example.com",
        status=VerificationRequestStatus.PENDING_ADMIN_REVIEW,
    )
    membership = SimpleNamespace(public_id=uuid4(), role=OrganizationRole.ADMIN, suspended_at=None)

    async def get_required_request(_public_id):
        return request

    async def get_membership_for_request(_request, _actor_id):
        return membership

    bind = VerificationRequestService
    service._get_required_request = get_required_request
    service._get_membership_for_request = get_membership_for_request
    service._assert_active_membership_access = bind._assert_active_membership_access.__get__(service, bind)
    service._is_subject_actor = bind._is_subject_actor.__get__(service, bind)

    with pytest.raises(
        ConflictError,
        match="Verification request is not awaiting organization acceptance",
    ):
        await service.accept(uuid4(), "hr@example.com", request.public_id)


@pytest.mark.asyncio
async def test_duplicate_organization_accept_is_safely_rejected() -> None:
    service = VerificationRequestService.__new__(VerificationRequestService)
    request = SimpleNamespace(
        public_id=uuid4(),
        organization_id=uuid4(),
        organization=SimpleNamespace(suspended_at=None),
        subject_user_id=uuid4(),
        subject_email="candidate@example.com",
        status=VerificationRequestStatus.IN_PROGRESS,
    )
    membership = SimpleNamespace(public_id=uuid4(), role=OrganizationRole.ADMIN, suspended_at=None)

    async def get_required_request(_public_id):
        return request

    async def get_membership_for_request(_request, _actor_id):
        return membership

    bind = VerificationRequestService
    service._get_required_request = get_required_request
    service._get_membership_for_request = get_membership_for_request
    service._assert_active_membership_access = bind._assert_active_membership_access.__get__(service, bind)
    service._is_subject_actor = bind._is_subject_actor.__get__(service, bind)

    with pytest.raises(
        ConflictError,
        match="Verification request is not awaiting organization acceptance",
    ):
        await service.accept(uuid4(), "hr@example.com", request.public_id)


@pytest.mark.asyncio
async def test_institution_member_can_accept_pending_organization_acceptance_for_education() -> None:
    service = VerificationRequestService.__new__(VerificationRequestService)
    actor_id = uuid4()
    education = SimpleNamespace(
        verification_status=EducationVerificationStatus.DRAFT.value,
    )
    request = SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        organization_id=uuid4(),
        organization=SimpleNamespace(public_id=uuid4(), suspended_at=None),
        subject_user_id=uuid4(),
        subject_email="candidate@example.com",
        status=VerificationRequestStatus.PENDING_ORGANIZATION_ACCEPTANCE,
        education_id=uuid4(),
    )
    membership = SimpleNamespace(public_id=uuid4(), role=OrganizationRole.REVIEWER, suspended_at=None)

    async def get_required_request(_public_id):
        return request

    async def get_membership_for_request(_request, _actor_id):
        return membership

    class Workflow:
        async def transition(self, target, *, target_status, **_kwargs):
            target.status = target_status

    async def commit_reload_org_response(_public_id, _actor_user_id):
        return request

    bind = VerificationRequestService
    service._get_required_request = get_required_request
    service._get_membership_for_request = get_membership_for_request
    service._workflow = Workflow()
    service._commit_reload_org_response = commit_reload_org_response
    service._assert_active_membership_access = bind._assert_active_membership_access.__get__(service, bind)
    service._is_subject_actor = bind._is_subject_actor.__get__(service, bind)

    result = await service.accept(actor_id, "registrar@example.edu", request.public_id)

    assert result is request
    assert request.status == VerificationRequestStatus.IN_PROGRESS
    assert education.verification_status == EducationVerificationStatus.DRAFT.value
