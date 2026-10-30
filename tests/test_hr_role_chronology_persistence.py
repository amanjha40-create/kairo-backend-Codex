"""Real PostgreSQL regressions for role responses and employment chronology."""

from datetime import date
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_hr_v2_service
from app.config import get_settings
from app.db.session import async_session_factory
from app.exceptions import ConflictError, ValidationAppError
from app.main import app
from app.models.organization import Organization
from app.models.organization_job_role import OrganizationJobRole
from app.models.organization_member import OrganizationMember
from app.models.organization_person import OrganizationPerson
from app.models.user import User
from app.organization.enums import OrganizationRole, OrganizationType
from app.schemas.hr_v2 import (
    EmployeeLifecycleUpdateRequest,
    FormerEmployeeCorrectionCreateRequest,
    FormerEmployeeCorrectionDecisionRequest,
    OrganizationRoleAssignmentRequest,
)
from app.services.hr_v2_service import HRV2Service

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _fixture(session, *, exited=True):
    actor = User(
        email=f"role-chronology-{uuid4()}@example.test",
        full_name="Synthetic HR",
        role="hr",
        is_active=True,
    )
    session.add(actor)
    await session.flush()
    organization = Organization(
        name=f"Synthetic Chronology {uuid4()}",
        created_by_user_id=actor.id,
        organization_type=OrganizationType.EMPLOYER,
    )
    session.add(organization)
    await session.flush()
    role = OrganizationJobRole(
        organization_id=organization.id,
        name="Synthetic Engineer",
        normalized_name="synthetic engineer",
        is_active=True,
    )
    session.add(role)
    await session.flush()
    person = OrganizationPerson(
        organization_id=organization.id,
        full_name="Synthetic Employee",
        added_by_user_id=actor.id,
        role_id=role.id,
        department="Before",
        joining_date=date(2024, 1, 1),
        employment_status="ex_employee" if exited else "active",
        last_working_day=date(2025, 1, 31) if exited else None,
    )
    session.add_all(
        [
            person,
            OrganizationMember(
                organization_id=organization.id, user_id=actor.id, role=OrganizationRole.OWNER
            ),
        ]
    )
    await session.commit()
    await session.refresh(person)
    await session.refresh(role)
    return HRV2Service(session, get_settings()), actor, organization, person, role


def _state(person):
    return (
        person.role_id,
        person.department,
        person.joining_date,
        person.last_working_day,
        person.employment_status,
        person.relationship,
        person.updated_at,
    )


async def test_deactivate_role_returns_loaded_committed_response_and_repeat_is_safe():
    async with async_session_factory() as session:
        service, actor, org, person, role = await _fixture(session)
        role_id, person_id = role.id, person.id
        for _ in range(2):
            result = await service.deactivate_role(actor.id, org.public_id, role.public_id)
            assert result.is_active is False
            assert result.updated_at is not None
            assert result.assigned_people_count == 1
            assert result.model_dump(mode="json")["updated_at"]
            async with async_session_factory() as reader:
                persisted = await reader.get(OrganizationJobRole, role_id)
                assigned_person = await reader.get(OrganizationPerson, person_id)
                assert persisted.is_active is False
                assert persisted.updated_at == result.updated_at
                assert assigned_person.role_id == role_id


@pytest.mark.parametrize("joining", [date(2024, 12, 31), date(2025, 1, 31)])
async def test_audited_correction_allows_joining_before_or_equal_to_exit(joining):
    async with async_session_factory() as session:
        service, actor, org, person, _ = await _fixture(session)
        correction = await service.create_former_employee_correction(
            actor.id,
            org.public_id,
            person.public_id,
            FormerEmployeeCorrectionCreateRequest(
                proposed_changes={"joining_date": joining.isoformat()},
                reason="Correct synthetic employment history",
            ),
        )
        await service.approve_former_employee_correction(
            actor.id,
            org.public_id,
            correction.public_id,
            FormerEmployeeCorrectionDecisionRequest(
                decision_reason="Verified synthetic correction"
            ),
        )
        async with async_session_factory() as reader:
            persisted = await reader.get(OrganizationPerson, person.id)
            assert persisted.joining_date == joining
            assert persisted.last_working_day == date(2025, 1, 31)


@pytest.mark.parametrize("exit_day", [date(2024, 1, 1), date(2025, 1, 31)])
async def test_lifecycle_exit_equal_or_after_joining_preserves_same_day_rule(exit_day):
    async with async_session_factory() as session:
        service, actor, org, person, _ = await _fixture(session, exited=False)
        result = await service.update_employee_lifecycle(
            actor.id,
            org.public_id,
            person.public_id,
            EmployeeLifecycleUpdateRequest(
                employment_status="ex_employee", last_working_day=exit_day
            ),
        )
        assert result.last_working_day == exit_day
        async with async_session_factory() as reader:
            persisted = await reader.get(OrganizationPerson, person.id)
            assert persisted.last_working_day == exit_day
            assert persisted.joining_date == date(2024, 1, 1)


async def test_invalid_correction_chronology_rejected_before_any_field_changes_or_commit():
    async with async_session_factory() as session:
        service, actor, org, person, _ = await _fixture(session)
        before = _state(person)
        correction = await service.create_former_employee_correction(
            actor.id,
            org.public_id,
            person.public_id,
            FormerEmployeeCorrectionCreateRequest(
                proposed_changes={
                    "department": "Must not persist",
                    "joining_date": "2025-02-01",
                },
                reason="Invalid synthetic correction",
            ),
        )
        with pytest.raises(
            ValidationAppError, match="joining_date cannot be after last_working_day"
        ):
            await service.approve_former_employee_correction(
                actor.id,
                org.public_id,
                correction.public_id,
                FormerEmployeeCorrectionDecisionRequest(),
            )
        assert _state(person) == before
        assert not session.is_modified(person)
        # Even if a caller subsequently commits, no rejected field may leak into storage.
        await session.commit()
        async with async_session_factory() as reader:
            assert _state(await reader.get(OrganizationPerson, person.id)) == before


async def test_invalid_exit_change_rejected_without_partial_mutation():
    async with async_session_factory() as session:
        service, actor, org, person, _ = await _fixture(session, exited=False)
        before = _state(person)
        with pytest.raises(
            ValidationAppError, match="last_working_day cannot be before joining_date"
        ):
            await service.update_employee_lifecycle(
                actor.id,
                org.public_id,
                person.public_id,
                EmployeeLifecycleUpdateRequest(
                    employment_status="ex_employee", last_working_day=date(2023, 12, 31)
                ),
            )
        assert _state(person) == before
        assert not session.is_modified(person)
        await session.commit()
        async with async_session_factory() as reader:
            assert _state(await reader.get(OrganizationPerson, person.id)) == before


async def test_lifecycle_cannot_rewrite_former_employee_exit_history():
    async with async_session_factory() as session:
        service, actor, org, person, _ = await _fixture(session)
        before = _state(person)
        with pytest.raises(ConflictError, match="Former-employee history is immutable"):
            await service.update_employee_lifecycle(
                actor.id,
                org.public_id,
                person.public_id,
                EmployeeLifecycleUpdateRequest(
                    employment_status="ex_employee",
                    last_working_day=date(2025, 1, 30),
                ),
            )
        assert _state(person) == before
        assert not session.is_modified(person)


async def test_unrelated_partial_edit_preserves_role_and_valid_chronology():
    async with async_session_factory() as session:
        service, actor, org, person, role = await _fixture(session, exited=False)
        result = await service.assign_role(
            actor.id,
            org.public_id,
            person.public_id,
            OrganizationRoleAssignmentRequest(department="After"),
        )
        assert result.department == "After"
        assert result.role_id == role.public_id
        async with async_session_factory() as reader:
            persisted = await reader.get(OrganizationPerson, person.id)
            assert persisted.role_id == role.id
            assert persisted.department == "After"
            assert persisted.joining_date == date(2024, 1, 1)
            assert persisted.last_working_day is None


@pytest.mark.parametrize("joining", [None, date(2025, 2, 1)])
async def test_optional_dates_remain_optional_when_no_exit_exists(joining):
    async with async_session_factory() as session:
        service, actor, org, person, _ = await _fixture(session, exited=False)
        result = await service.assign_role(
            actor.id,
            org.public_id,
            person.public_id,
            OrganizationRoleAssignmentRequest(joining_date=joining),
        )
        assert result.joining_date == joining
        await session.refresh(person)
        assert person.last_working_day is None


async def test_normal_profile_edit_cannot_clear_former_employee_joining_date():
    async with async_session_factory() as session:
        service, actor, org, person, _ = await _fixture(session)
        with pytest.raises(ConflictError, match="Former-employee history is immutable"):
            await service.assign_role(
                actor.id,
                org.public_id,
                person.public_id,
                OrganizationRoleAssignmentRequest(joining_date=None),
            )
        await session.refresh(person)
        assert person.joining_date == date(2024, 1, 1)
        assert person.last_working_day == date(2025, 1, 31)


async def test_former_employee_edit_uses_existing_http_conflict_envelope():
    async with async_session_factory() as session:
        service, actor, org, person, _ = await _fixture(session)
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=actor.id, email=actor.email, role="hr"
        )
        app.dependency_overrides[get_hr_v2_service] = lambda: service
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.patch(
                    f"/api/v1/organizations/{org.public_id}/people/{person.public_id}/employment-profile",
                    json={"joining_date": "2025-02-01", "department": "Must not persist"},
                )
            assert response.status_code == 409
            assert response.json()["error"]["code"] == "conflict"
            assert (
                "Former-employee history is immutable"
                in response.json()["error"]["message"]
            )
            await session.refresh(person)
            assert person.department == "Before" and person.joining_date == date(2024, 1, 1)
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_hr_v2_service, None)
