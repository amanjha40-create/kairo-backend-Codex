"""Focused service regressions for institution workspace read models."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.exceptions import ForbiddenError, NotFoundError
from app.institution_people.enums import (
    InstitutionCredentialStatus,
    InstitutionPersonLifecycleStatus,
    InstitutionVerificationStatus,
)
from app.organization.enums import OrganizationType
from app.schemas.institution_workspace import InstitutionVerificationInboxQuery
from app.schemas.pagination import ListQueryParams
from app.schemas.verification_request import VerificationRequestEvidenceResponse
from app.services.institution_workspace_service import InstitutionWorkspaceService


def _credential(*, title: str = "Bachelor of Science") -> SimpleNamespace:
    return SimpleNamespace(
        public_id=uuid4(),
        title=title,
        credential_type="degree",
        status=InstitutionCredentialStatus.ISSUED,
        updated_at=datetime.now(tz=UTC),
    )


def _profile(
    *,
    lifecycle_status: str = InstitutionPersonLifecycleStatus.ALUMNI.value,
    verification_status: InstitutionVerificationStatus = InstitutionVerificationStatus.PENDING,
    credentials: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        lifecycle_status=lifecycle_status,
        institution_verification_status=verification_status,
        credentials=credentials or [],
    )


def _request(
    *,
    status: str,
    request_type: str = "education",
    priority: str = "normal",
    education_name: str = "Kairo University",
    degree: str = "BSc Computer Science",
) -> SimpleNamespace:
    now = datetime.now(tz=UTC)
    return SimpleNamespace(
        public_id=uuid4(),
        status=status,
        request_type=request_type,
        priority=priority,
        due_date=None,
        created_at=now,
        updated_at=now,
        assigned_to_user_id=None,
        subject_name="Synthetic Student",
        subject_email="student@example.test",
        education=SimpleNamespace(
            institution_name=education_name,
            degree=degree,
            field_of_study="Computer Science",
        ),
    )


def _identity_consent_filter(_request_obj: object, items: list[object]) -> list[object]:
    return items


@pytest.mark.asyncio
async def test_institution_dashboard_handles_string_statuses_and_quality_review() -> None:
    service = InstitutionWorkspaceService.__new__(InstitutionWorkspaceService)
    organization = SimpleNamespace(id=uuid4())
    service._require_university_access = AsyncMock(return_value=(organization, None))
    service._requests_for_organization = AsyncMock(
        return_value=[
            _request(status="pending_organization_acceptance", priority="high"),
            _request(status="pending_admin_quality_review"),
            _request(status="awaiting_information"),
            _request(status="verified"),
        ]
    )
    service._people = SimpleNamespace(
        list_profiles=AsyncMock(
            return_value=[
                _profile(
                    lifecycle_status=InstitutionPersonLifecycleStatus.CURRENT_STUDENT.value,
                    verification_status=InstitutionVerificationStatus.VERIFIED,
                    credentials=[_credential()],
                ),
                _profile(lifecycle_status=InstitutionPersonLifecycleStatus.ALUMNI.value),
            ]
        )
    )
    service._recent_events = AsyncMock(
        return_value=[
            (
                SimpleNamespace(
                    event_type="verification_completed",
                    event_source="organization",
                    created_at=datetime.now(tz=UTC),
                ),
                uuid4(),
            )
        ]
    )

    result = await service.dashboard(uuid4(), uuid4())

    assert result.pending_verifications == 2
    assert result.statistics.total_verifications == 4
    assert result.statistics.verified_verifications == 1
    assert result.statistics.awaiting_information == 1
    assert result.statistics.high_priority == 1
    assert result.people.current_student == 1
    assert result.people.alumni == 1
    assert len(result.recently_verified_credentials) == 1
    assert result.verification_activity[0].event_type == "verification_completed"


@pytest.mark.asyncio
async def test_institution_inbox_filters_terminal_requests_with_string_statuses() -> None:
    service = InstitutionWorkspaceService.__new__(InstitutionWorkspaceService)
    organization = SimpleNamespace(id=uuid4())
    service._require_university_access = AsyncMock(return_value=(organization, None))
    service._requests_for_organization = AsyncMock(
        return_value=[
            _request(status="verified", priority="urgent", education_name="Kairo University"),
            _request(
                status="pending_organization_acceptance",
                priority="high",
                education_name="Other University",
            ),
        ]
    )

    response = await service.list_verifications(
        uuid4(),
        uuid4(),
        InstitutionVerificationInboxQuery(
            status="verified",
            request_type="education",
            search="kairo",
            page=1,
            page_size=10,
        ),
    )

    assert response.total == 1
    assert len(response.items) == 1
    assert response.items[0].status.value == "verified"
    assert response.items[0].request_type.value == "education"


@pytest.mark.asyncio
async def test_institution_verification_evidence_returns_consented_downloadable_items() -> None:
    service = InstitutionWorkspaceService.__new__(InstitutionWorkspaceService)
    organization = SimpleNamespace(id=uuid4())
    request = SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        status="verified",
        consented_evidence_scope=["transcript"],
    )
    evidence = SimpleNamespace(
        public_id=uuid4(),
        evidence_type="transcript",
        field_key="education_evidence",
    )
    response = VerificationRequestEvidenceResponse(
        public_id=evidence.public_id,
        evidence_type="transcript",
        field_key="education_evidence",
        document_id=None,
        employment_document_id=None,
        education_document_id=uuid4(),
        value=None,
        status="submitted",
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
        document_type="transcript",
        original_filename="transcript.pdf",
        mime_type="application/pdf",
        file_size=1024,
        upload_status="uploaded",
        download_url="https://example.test/transcript.pdf",
        download_url_expires_in_seconds=300,
    )
    service._require_university_access = AsyncMock(return_value=(organization, None))
    service._get_academic_request = AsyncMock(return_value=request)
    service._verification_evidence = SimpleNamespace(
        list_for_request=AsyncMock(return_value=[evidence])
    )
    service._verification_service = SimpleNamespace(
        _filter_evidence_by_consent=_identity_consent_filter,
        _to_evidence_response=AsyncMock(return_value=response),
    )

    result = await service.list_verification_evidence(
        uuid4(),
        uuid4(),
        uuid4(),
        ListQueryParams(page=1, page_size=10),
    )

    assert result.total == 1
    assert result.items[0].download_url == "https://example.test/transcript.pdf"
    service._verification_service._to_evidence_response.assert_awaited_once_with(
        evidence,
        include_download_url=True,
    )


@pytest.mark.asyncio
async def test_institution_verification_evidence_returns_truthful_empty_page() -> None:
    service = InstitutionWorkspaceService.__new__(InstitutionWorkspaceService)
    organization = SimpleNamespace(id=uuid4())
    request = SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        status="verified",
        consented_evidence_scope=[],
    )
    service._require_university_access = AsyncMock(return_value=(organization, None))
    service._get_academic_request = AsyncMock(return_value=request)
    service._verification_evidence = SimpleNamespace(list_for_request=AsyncMock(return_value=[]))
    service._verification_service = SimpleNamespace(
        _filter_evidence_by_consent=_identity_consent_filter,
        _to_evidence_response=AsyncMock(),
    )

    result = await service.list_verification_evidence(
        uuid4(),
        uuid4(),
        uuid4(),
        ListQueryParams(page=1, page_size=10),
    )

    assert result.total == 0
    assert result.items == []


@pytest.mark.asyncio
async def test_institution_timeline_hides_internal_and_org_private_events() -> None:
    service = InstitutionWorkspaceService.__new__(InstitutionWorkspaceService)
    organization = SimpleNamespace(id=uuid4())
    request = SimpleNamespace(id=uuid4(), public_id=uuid4())
    rows = [
        SimpleNamespace(
            public_id=uuid4(),
            event_type="verification_request_created",
            event_source="candidate",
            previous_status=None,
            new_status="pending_subject_submission",
            metadata_payload={},
            created_at=datetime.now(tz=UTC),
        ),
        SimpleNamespace(
            public_id=uuid4(),
            event_type="verification_request_internal_note_updated",
            event_source="organization",
            previous_status=None,
            new_status=None,
            metadata_payload={"visibility": "organization_internal"},
            created_at=datetime.now(tz=UTC),
        ),
        SimpleNamespace(
            public_id=uuid4(),
            event_type="verification_request_admin_note_added",
            event_source="admin",
            previous_status=None,
            new_status=None,
            metadata_payload={"visibility": "internal"},
            created_at=datetime.now(tz=UTC),
        ),
        SimpleNamespace(
            public_id=uuid4(),
            event_type="verification_request_verified",
            event_source="admin",
            previous_status="pending_admin_quality_review",
            new_status="verified",
            metadata_payload={"decision_summary": "Confirmed"},
            created_at=datetime.now(tz=UTC),
        ),
    ]
    service._require_university_access = AsyncMock(return_value=(organization, None))
    service._get_academic_request = AsyncMock(return_value=request)
    service._verification_requests = SimpleNamespace(list_timeline=AsyncMock(return_value=rows))

    result = await service.get_verification_timeline(
        uuid4(),
        uuid4(),
        uuid4(),
        ListQueryParams(page=1, page_size=10),
    )

    assert result.total == 2
    assert [item.event_type for item in result.items] == [
        "verification_request_verified",
        "verification_request_created",
    ]


@pytest.mark.asyncio
async def test_require_university_access_fails_closed_without_membership() -> None:
    service = InstitutionWorkspaceService.__new__(InstitutionWorkspaceService)
    organization = SimpleNamespace(
        id=uuid4(),
        organization_type=OrganizationType.UNIVERSITY,
        suspended_at=None,
    )
    service._organizations = SimpleNamespace(
        get_by_public_id=AsyncMock(return_value=organization),
        get_membership=AsyncMock(return_value=None),
    )

    with pytest.raises(NotFoundError, match="Organization not found"):
        await service._require_university_access(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_require_university_access_denies_revoked_membership() -> None:
    service = InstitutionWorkspaceService.__new__(InstitutionWorkspaceService)
    organization = SimpleNamespace(
        id=uuid4(),
        organization_type=OrganizationType.UNIVERSITY,
        suspended_at=None,
    )
    membership = SimpleNamespace(suspended_at=datetime.now(tz=UTC))
    service._organizations = SimpleNamespace(
        get_by_public_id=AsyncMock(return_value=organization),
        get_membership=AsyncMock(return_value=membership),
    )

    with pytest.raises(
        ForbiddenError,
        match="Organization access is suspended|Organization membership is suspended",
    ):
        await service._require_university_access(uuid4(), uuid4())
