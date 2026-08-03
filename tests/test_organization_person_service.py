"""Focused unit tests for OrganizationPersonService resolution rules."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.organization_person import OrganizationPerson
from app.organization_people.enums import OrganizationPersonRelationship
from app.services.organization_person_service import OrganizationPersonService


def _build_service() -> OrganizationPersonService:
    service = OrganizationPersonService.__new__(OrganizationPersonService)
    service._session = SimpleNamespace(flush=AsyncMock(), refresh=AsyncMock())
    service._repo = SimpleNamespace(
        get_by_id=AsyncMock(return_value=None),
        find_by_linked_user=AsyncMock(return_value=None),
        find_by_primary_email=AsyncMock(return_value=None),
        find_by_primary_phone=AsyncMock(return_value=None),
        find_by_identifier=AsyncMock(return_value=None),
        create=AsyncMock(),
        get_identifier=AsyncMock(return_value=None),
        create_identifier=AsyncMock(),
    )
    service._users = SimpleNamespace(get_by_id=AsyncMock(return_value=None))
    service._employments = SimpleNamespace(get_active_by_id=AsyncMock(return_value=None))
    return service


@pytest.mark.asyncio
async def test_resolve_person_prefers_existing_person_link() -> None:
    service = _build_service()
    existing_person_id = uuid4()
    existing = OrganizationPerson(
        organization_id=uuid4(),
        full_name="Existing Person",
        relationship=OrganizationPersonRelationship.CANDIDATE,
        added_at=datetime.now(tz=UTC),
        resolution_state="resolved",
    )
    existing.id = existing_person_id
    existing.public_id = uuid4()
    service._repo.get_by_id = AsyncMock(return_value=existing)  # type: ignore[attr-defined]

    result = await service._resolve_person(  # type: ignore[attr-defined]
        organization_id=existing.organization_id,
        existing_person_id=existing_person_id,
        linked_user_id=None,
        full_name="Updated Name",
        email="candidate@example.com",
        phone=None,
        relationship=OrganizationPersonRelationship.FUTURE_EMPLOYEE,
        added_by_user_id=uuid4(),
        added_at=datetime.now(tz=UTC),
        last_activity_at=datetime.now(tz=UTC),
        source_type="trust_invitation",
        source_public_id=uuid4(),
        actor_user_id=uuid4(),
    )

    assert result is existing
    assert existing.resolution_method == "existing_link"
    assert Decimal(existing.resolution_confidence) == Decimal("1.00")
    service._repo.find_by_linked_user.assert_not_called()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_resolve_person_matches_existing_linked_user_before_email() -> None:
    service = _build_service()
    linked_user_id = uuid4()
    matched = OrganizationPerson(
        organization_id=uuid4(),
        full_name="Linked Person",
        relationship=OrganizationPersonRelationship.CANDIDATE,
        added_at=datetime.now(tz=UTC),
        resolution_state="resolved",
        linked_user_id=linked_user_id,
    )
    matched.id = uuid4()
    matched.public_id = uuid4()
    service._repo.find_by_linked_user = AsyncMock(return_value=matched)  # type: ignore[attr-defined]

    result = await service._resolve_person(  # type: ignore[attr-defined]
        organization_id=matched.organization_id,
        existing_person_id=None,
        linked_user_id=linked_user_id,
        full_name="Linked Person",
        email="linked@example.com",
        phone=None,
        relationship=OrganizationPersonRelationship.CANDIDATE,
        added_by_user_id=uuid4(),
        added_at=datetime.now(tz=UTC),
        last_activity_at=datetime.now(tz=UTC),
        source_type="verification_request",
        source_public_id=uuid4(),
        actor_user_id=uuid4(),
    )

    assert result is matched
    assert matched.resolution_method == "linked_user"
    service._repo.find_by_primary_email.assert_not_called()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_resolve_person_creates_new_record_when_no_match_exists() -> None:
    service = _build_service()

    result = await service._resolve_person(  # type: ignore[attr-defined]
        organization_id=uuid4(),
        existing_person_id=None,
        linked_user_id=None,
        full_name="New Candidate",
        email="new@example.com",
        phone="+1 (555) 111-2222",
        relationship=OrganizationPersonRelationship.CANDIDATE,
        added_by_user_id=uuid4(),
        added_at=datetime.now(tz=UTC),
        last_activity_at=datetime.now(tz=UTC),
        source_type="trust_invitation",
        source_public_id=uuid4(),
        actor_user_id=uuid4(),
    )

    assert isinstance(result, OrganizationPerson)
    assert result.full_name == "New Candidate"
    assert result.primary_email == "new@example.com"
    assert result.primary_phone == "+15551112222"
    assert result.resolution_method == "created"
    service._repo.create.assert_awaited_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_resolve_verification_request_loads_events_before_activity_projection() -> None:
    service = _build_service()
    person = SimpleNamespace(id=uuid4())
    service._resolve_person = AsyncMock(return_value=person)  # type: ignore[attr-defined]
    request = SimpleNamespace(
        organization_id=uuid4(),
        organization_person_id=None,
        subject_user_id=None,
        employment_id=None,
        subject_name="Candidate",
        subject_email="candidate@example.com",
        requested_by_user_id=uuid4(),
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
        candidate_response_submitted_at=None,
        accepted_at=None,
        events=[],
        public_id=uuid4(),
    )

    result = await service.resolve_for_verification_request(request)

    assert result is person
    service._session.refresh.assert_awaited_once_with(request, attribute_names=["events"])  # type: ignore[attr-defined]
    assert request.organization_person_id == person.id
