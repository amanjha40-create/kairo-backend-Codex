"""Regression coverage for async-safe verification request serialization."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.organization import Organization
from app.models.verification_request import VerificationRequest
from app.organization.enums import OrganizationType, OrganizationVerificationState
from app.repositories.verification_request import VerificationRequestRepository
from app.services.verification_request_service import VerificationRequestService
from app.verification_requests.enums import (
    VerificationRequestOriginType,
    VerificationRequestStatus,
    VerificationRequestType,
)


class _FakeScalarResult:
    def __init__(self, value) -> None:  # noqa: ANN001
        self._value = value

    def first(self):  # noqa: ANN201
        return self._value

    def all(self):  # noqa: ANN201
        return [self._value]


class _FakeExecuteResult:
    def __init__(self, value) -> None:  # noqa: ANN001
        self._value = value

    def scalar_one_or_none(self):  # noqa: ANN201
        return self._value

    def scalars(self) -> _FakeScalarResult:
        return _FakeScalarResult(self._value)


class _FakeSession:
    def __init__(self, value) -> None:  # noqa: ANN001
        self.value = value
        self.captured_stmt = None

    async def execute(self, stmt):  # noqa: ANN001
        self.captured_stmt = stmt
        return _FakeExecuteResult(self.value)


def _relationship_paths(stmt) -> set[str]:  # noqa: ANN001
    return {str(option.path) for option in stmt._with_options}


EXPECTED_RESPONSE_RELATIONSHIPS = {
    (
        "ORM Path[Mapper[VerificationRequest(verification_requests)] -> "
        "VerificationRequest.organization -> Mapper[Organization(organizations)]]"
    ),
    (
        "ORM Path[Mapper[VerificationRequest(verification_requests)] -> "
        "VerificationRequest.registry_record -> "
        "Mapper[TrustRegistryRecord(trust_registry_records)]]"
    ),
    (
        "ORM Path[Mapper[VerificationRequest(verification_requests)] -> "
        "VerificationRequest.trust_invitation -> Mapper[TrustInvitation(trust_invitations)]]"
    ),
}


def _build_request(*, with_organization: bool) -> VerificationRequest:
    request = VerificationRequest(
        origin_type=VerificationRequestOriginType.SUBJECT_INITIATED,
        subject_user_id=uuid4(),
        subject_name="Candidate One",
        subject_email="candidate@example.com",
        target_organization_name="Northstar Technologies",
        target_organization_email="hr@northstar.example",
        request_type=VerificationRequestType.EMPLOYMENT,
        status=VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION,
        requested_by_user_id=uuid4(),
        trust_context={"source": "subject"},
    )
    request.id = uuid4()
    request.public_id = uuid4()
    request.employment_id = uuid4()
    request.created_at = datetime.now(tz=UTC)
    request.updated_at = request.created_at
    request.consented_fields = []
    request.consented_evidence_scope = []
    request.target_organization_metadata = {"channel": "candidate"}
    if with_organization:
        request.organization = Organization(
            created_by_user_id=uuid4(),
            name="Northstar Technologies",
            organization_type=OrganizationType.EMPLOYER,
            verification_state=OrganizationVerificationState.VERIFIED,
        )
        request.organization.public_id = uuid4()
        request.organization.suspended_at = None
    else:
        request.organization = None
    request.trust_invitation = None
    return request


def _build_service() -> VerificationRequestService:
    service = VerificationRequestService.__new__(VerificationRequestService)
    service._evidence = SimpleNamespace(list_for_request=AsyncMock(return_value=[]))
    service._employments = SimpleNamespace(
        get_active_by_id=AsyncMock(
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
    )
    service._educations = SimpleNamespace(get_active_by_id=AsyncMock(return_value=None))
    service._users = SimpleNamespace(get_by_id=AsyncMock(return_value=None))
    return service


@pytest.mark.asyncio
async def test_get_active_for_employment_preloads_response_relationships() -> None:
    session = _FakeSession(None)
    repo = VerificationRequestRepository(session)  # type: ignore[arg-type]

    await repo.get_active_for_employment(uuid4())

    assert session.captured_stmt is not None
    assert _relationship_paths(session.captured_stmt) == EXPECTED_RESPONSE_RELATIONSHIPS


@pytest.mark.asyncio
async def test_get_active_for_education_preloads_response_relationships() -> None:
    session = _FakeSession(None)
    repo = VerificationRequestRepository(session)  # type: ignore[arg-type]

    await repo.get_active_for_education(uuid4())

    assert session.captured_stmt is not None
    assert _relationship_paths(session.captured_stmt) == EXPECTED_RESPONSE_RELATIONSHIPS


@pytest.mark.asyncio
async def test_get_by_public_id_preloads_response_relationships_for_new_draft_reload() -> None:
    session = _FakeSession(None)
    repo = VerificationRequestRepository(session)  # type: ignore[arg-type]

    await repo.get_by_public_id(uuid4())

    assert session.captured_stmt is not None
    assert _relationship_paths(session.captured_stmt) == EXPECTED_RESPONSE_RELATIONSHIPS


@pytest.mark.asyncio
async def test_subject_response_serializes_loaded_organization_public_id() -> None:
    service = _build_service()
    request = _build_request(with_organization=True)

    response = await service._to_subject_response(request)  # type: ignore[attr-defined]

    assert response.public_id == request.public_id
    assert response.employment_id == request.employment_id
    assert response.organization_public_id == request.organization.public_id
    assert response.status == VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION


@pytest.mark.asyncio
async def test_subject_response_serializes_without_organization() -> None:
    service = _build_service()
    request = _build_request(with_organization=False)

    response = await service._to_subject_response(request)  # type: ignore[attr-defined]

    assert response.public_id == request.public_id
    assert response.employment_id == request.employment_id
    assert response.organization_public_id is None
    assert response.status == VerificationRequestStatus.PENDING_SUBJECT_SUBMISSION
