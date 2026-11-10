"""Canonical Candidate-directory classification regressions."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.auth.deps import CurrentUser
from app.config import get_settings
from app.core.constants import Role
from app.db.session import async_session_factory
from app.exceptions import NotFoundError
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.organization.enums import OrganizationRole, OrganizationType
from app.schemas.pagination import ListQueryParams
from app.services.admin_directory_service import AdminDirectoryService


@pytest.mark.integration
@pytest.mark.asyncio
async def test_candidate_directory_excludes_hr_only_and_preserves_dual_role_users() -> None:
    marker = uuid4().hex
    now = datetime.now(tz=UTC)
    async with async_session_factory() as session:
        admin = User(
            email=f"admin-classification-{marker}@example.invalid",
            full_name="Classification Admin",
            role=Role.ADMIN.value,
            is_active=True,
            email_verified_at=now,
        )
        candidate = User(
            email=f"candidate-classification-{marker}@example.invalid",
            full_name=f"Classification Candidate {marker}",
            role=Role.USER.value,
            is_active=True,
            email_verified_at=now,
            phone_verified_at=now,
        )
        hr_only = User(
            email=f"hr-classification-{marker}@example.invalid",
            full_name=f"Classification HR {marker}",
            role=Role.USER.value,
            is_active=True,
            email_verified_at=now,
        )
        dual_role = User(
            email=f"dual-classification-{marker}@example.invalid",
            full_name=f"Classification Dual {marker}",
            role=Role.USER.value,
            is_active=True,
            email_verified_at=now,
            phone_verified_at=now,
        )
        session.add_all([admin, candidate, hr_only, dual_role])
        await session.flush()

        organization = Organization(
            created_by_user_id=admin.id,
            name=f"Classification Client {marker}",
            organization_type=OrganizationType.EMPLOYER,
        )
        session.add(organization)
        await session.flush()
        session.add_all(
            [
                OrganizationMember(
                    organization_id=organization.id,
                    user_id=hr_only.id,
                    role=OrganizationRole.OWNER,
                ),
                OrganizationMember(
                    organization_id=organization.id,
                    user_id=dual_role.id,
                    role=OrganizationRole.MEMBER,
                ),
            ]
        )
        await session.commit()

        service = AdminDirectoryService(session, get_settings())
        page = await service.list_users(
            ListQueryParams(search=marker, status="active", page=1, page_size=20)
        )
        ids = {item.public_id for item in page.items}

        assert page.total == 2
        assert ids == {candidate.id, dual_role.id}
        hr_page = await service.list_users(
            ListQueryParams(search=hr_only.email, page=1, page_size=20)
        )
        assert hr_page.total == 0
        assert hr_page.items == []

        actor = CurrentUser(
            id=admin.id,
            email=admin.email,
            role=Role.ADMIN.value,
            full_name=admin.full_name,
        )
        assert (await service.get_user_detail(actor, candidate.id)).public_id == candidate.id
        assert (await service.get_user_detail(actor, dual_role.id)).public_id == dual_role.id
        with pytest.raises(NotFoundError, match="Candidate not found"):
            await service.get_user_detail(actor, hr_only.id)

        await session.delete(organization)
        await session.flush()
        for user in (candidate, hr_only, dual_role, admin):
            await session.delete(user)
        await session.commit()
