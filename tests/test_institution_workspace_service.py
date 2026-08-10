"""Focused service regressions for institution workspace read models."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.institution_people.enums import (
    InstitutionCredentialStatus,
    InstitutionPersonLifecycleStatus,
    InstitutionVerificationStatus,
)
from app.schemas.institution_workspace import InstitutionVerificationInboxQuery
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
