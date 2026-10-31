"""Focused regressions for HR V1.0.1 correction review and role creator display."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db.session import async_session_factory
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.main import app
from app.models.organization import Organization
from app.models.organization_activity_event import OrganizationActivityEvent
from app.models.organization_member import OrganizationMember
from app.models.organization_person import OrganizationPerson
from app.models.user import User
from app.organization.enums import OrganizationRole, OrganizationType
from app.schemas.hr_v2 import (
    FormerEmployeeCorrectionCreateRequest,
    FormerEmployeeCorrectionDecisionRequest,
    FormerEmployeeCorrectionListQuery,
    OrganizationJobRoleCreateRequest,
)
from app.services.hr_v2_service import HRV2Service

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _fixture(session):  # noqa: ANN001
    owner = User(
        email=f"hr-owner-{uuid4()}@example.com",
        full_name="Synthetic Owner",
        role="hr",
        is_active=True,
    )
    admin = User(
        email=f"hr-admin-{uuid4()}@example.com",
        full_name="Synthetic Admin",
        role="hr",
        is_active=True,
    )
    member = User(
        email=f"hr-member-{uuid4()}@example.com",
        full_name=None,
        role="hr",
        is_active=True,
    )
    other_owner = User(
        email=f"hr-other-owner-{uuid4()}@example.com",
        full_name="Other Owner",
        role="hr",
        is_active=True,
    )
    session.add_all([owner, admin, member, other_owner])
    await session.flush()

    organization = Organization(
        name=f"Synthetic HR Review {uuid4()}",
        created_by_user_id=owner.id,
        organization_type=OrganizationType.EMPLOYER,
    )
    other_organization = Organization(
        name=f"Synthetic Other HR Review {uuid4()}",
        created_by_user_id=other_owner.id,
        organization_type=OrganizationType.EMPLOYER,
    )
    session.add_all([organization, other_organization])
    await session.flush()
    session.add_all(
        [
            OrganizationMember(
                organization_id=organization.id,
                user_id=owner.id,
                role=OrganizationRole.OWNER,
            ),
            OrganizationMember(
                organization_id=organization.id,
                user_id=admin.id,
                role=OrganizationRole.ADMIN,
            ),
            OrganizationMember(
                organization_id=organization.id,
                user_id=member.id,
                role=OrganizationRole.MEMBER,
            ),
            OrganizationMember(
                organization_id=other_organization.id,
                user_id=other_owner.id,
                role=OrganizationRole.OWNER,
            ),
        ]
    )
    person = OrganizationPerson(
        organization_id=organization.id,
        full_name="Synthetic Former Employee",
        added_by_user_id=owner.id,
        employment_status="ex_employee",
        last_working_day=date(2025, 1, 31),
        department="Before",
    )
    session.add(person)
    await session.commit()
    return SimpleNamespace(
        service=HRV2Service(session, get_settings()),
        organization=organization,
        other_organization=other_organization,
        owner=owner,
        admin=admin,
        member=member,
        other_owner=other_owner,
        person=person,
    )


async def test_correction_queue_is_manager_only_paginated_and_tenant_isolated() -> None:
    async with async_session_factory() as session:
        case = await _fixture(session)
        created = await case.service.create_former_employee_correction(
            case.member.id,
            case.organization.public_id,
            case.person.public_id,
            FormerEmployeeCorrectionCreateRequest(
                proposed_changes={"department": "After"},
                reason="Correct the synthetic department",
            ),
        )

        for manager in (case.owner, case.admin):
            page = await case.service.list_former_employee_corrections(
                manager.id,
                case.organization.public_id,
                FormerEmployeeCorrectionListQuery(status="pending", page=1, page_size=10),
            )
            assert page.total == 1 and page.page == 1 and page.page_size == 10
            assert page.items[0].public_id == created.public_id
            assert page.items[0].person.display_name == "Synthetic Former Employee"
            assert page.items[0].current_values["department"] == "Before"
            assert page.items[0].proposed_values["department"] == "After"
            assert page.items[0].reason == "Correct the synthetic department"
            assert page.items[0].requester.email == case.member.email
            assert page.items[0].requester.display_name == case.member.email
            assert page.items[0].reviewer is None

        with pytest.raises(ForbiddenError):
            await case.service.list_former_employee_corrections(
                case.member.id,
                case.organization.public_id,
                FormerEmployeeCorrectionListQuery(),
            )
        with pytest.raises(NotFoundError):
            await case.service.list_former_employee_corrections(
                case.other_owner.id,
                case.organization.public_id,
                FormerEmployeeCorrectionListQuery(),
            )
        other_page = await case.service.list_former_employee_corrections(
            case.other_owner.id,
            case.other_organization.public_id,
            FormerEmployeeCorrectionListQuery(),
        )
        assert other_page.total == 0


async def test_approved_and_rejected_corrections_filter_and_preserve_audit() -> None:
    async with async_session_factory() as session:
        case = await _fixture(session)
        approved = await case.service.create_former_employee_correction(
            case.member.id,
            case.organization.public_id,
            case.person.public_id,
            FormerEmployeeCorrectionCreateRequest(
                proposed_changes={"department": "Approved Department"},
                reason="Approve this synthetic correction",
            ),
        )
        await case.service.approve_former_employee_correction(
            case.owner.id,
            case.organization.public_id,
            approved.public_id,
            FormerEmployeeCorrectionDecisionRequest(decision_reason="Synthetic approval"),
        )
        with pytest.raises(ConflictError):
            await case.service.approve_former_employee_correction(
                case.owner.id,
                case.organization.public_id,
                approved.public_id,
                FormerEmployeeCorrectionDecisionRequest(),
            )

        rejected = await case.service.create_former_employee_correction(
            case.member.id,
            case.organization.public_id,
            case.person.public_id,
            FormerEmployeeCorrectionCreateRequest(
                proposed_changes={"department": "Must Not Apply"},
                reason="Reject this synthetic correction",
            ),
        )
        await case.service.reject_former_employee_correction(
            case.admin.id,
            case.organization.public_id,
            rejected.public_id,
            FormerEmployeeCorrectionDecisionRequest(decision_reason="Synthetic rejection"),
        )
        await session.refresh(case.person)
        assert case.person.department == "Approved Department"

        pending = await case.service.list_former_employee_corrections(
            case.owner.id,
            case.organization.public_id,
            FormerEmployeeCorrectionListQuery(status="pending"),
        )
        approved_page = await case.service.list_former_employee_corrections(
            case.owner.id,
            case.organization.public_id,
            FormerEmployeeCorrectionListQuery(status="approved"),
        )
        rejected_page = await case.service.list_former_employee_corrections(
            case.owner.id,
            case.organization.public_id,
            FormerEmployeeCorrectionListQuery(status="rejected"),
        )
        assert pending.total == 0
        assert approved_page.total == 1
        assert approved_page.items[0].reviewer.display_name == case.owner.full_name
        assert approved_page.items[0].decided_at is not None
        assert rejected_page.total == 1
        assert rejected_page.items[0].proposed_values["department"] == "Must Not Apply"
        assert rejected_page.items[0].reviewer.display_name == case.admin.full_name

        event_counts = dict(
            (
                await session.execute(
                    select(OrganizationActivityEvent.event_type, func.count())
                    .where(OrganizationActivityEvent.organization_id == case.organization.id)
                    .group_by(OrganizationActivityEvent.event_type)
                )
            ).all()
        )
        assert event_counts["former_employee_correction_requested"] == 2
        assert event_counts["former_employee_correction_approved"] == 1
        assert event_counts["former_employee_correction_rejected"] == 1


async def test_hiring_role_creator_and_approver_use_safe_team_identity() -> None:
    async with async_session_factory() as session:
        case = await _fixture(session)
        member_role = await case.service.create_role(
            case.member.id,
            case.organization.public_id,
            OrganizationJobRoleCreateRequest(
                name=f"Synthetic Member Role {uuid4()}", mode="submit"
            ),
        )
        assert member_role.status == "pending_approval"
        assert member_role.created_by.display_name == case.member.email
        assert member_role.created_by.email == case.member.email
        assert "id" not in member_role.created_by.model_dump()
        assert member_role.created_by.display_name != str(case.member.id)

        approved = await case.service.approve_role(
            case.owner.id,
            case.organization.public_id,
            member_role.public_id,
        )
        assert approved.created_by.display_name == case.member.email
        assert approved.approved_by.display_name == "Synthetic Owner"

        owner_role = await case.service.create_role(
            case.owner.id,
            case.organization.public_id,
            OrganizationJobRoleCreateRequest(name=f"Synthetic Owner Role {uuid4()}", mode="submit"),
        )
        assert owner_role.status == "active"
        assert owner_role.created_by.display_name == "Synthetic Owner"
        assert owner_role.approved_by.display_name == "Synthetic Owner"
        assert owner_role.created_by_user_id == case.owner.id


async def test_openapi_exposes_paginated_correction_queue_and_safe_role_summaries() -> None:
    schema = app.openapi()
    operation = schema["paths"]["/api/v1/organizations/{org_public_id}/people/corrections"]["get"]
    query_names = {parameter["name"] for parameter in operation["parameters"]}
    role_properties = schema["components"]["schemas"]["OrganizationJobRoleResponse"]["properties"]

    assert {"status", "page", "page_size", "offset", "limit"} <= query_names
    assert {"created_by", "approved_by"} <= set(role_properties)
