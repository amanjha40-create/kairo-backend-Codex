"""Focused regression coverage for workspace bootstrap state derivation."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.organization.enums import OrganizationRole, OrganizationType, OrganizationVerificationState
from app.schemas.workspace import WorkspaceAccessState
from app.services.workspace_service import WorkspaceService


def _build_user(*, active_organization_id=None):
    return SimpleNamespace(
        id=uuid4(),
        email="owner@kairo.example",
        full_name="Owner User",
        role="user",
        active_organization_id=active_organization_id,
    )


def _build_organization(
    *,
    organization_type: OrganizationType = OrganizationType.EMPLOYER,
    verification_state: OrganizationVerificationState = OrganizationVerificationState.VERIFIED,
    setup_completed_at: datetime | None = None,
    suspended_at: datetime | None = None,
):
    now = datetime.now(tz=UTC)
    return SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        name="Kairo Org",
        organization_type=organization_type,
        website="https://kairo.example",
        industry="Software",
        location="Bengaluru, IN",
        work_email="owner@kairo.example",
        domain="kairo.example",
        organization_size=None,
        hiring_volume=None,
        domain_verified_at=None,
        verification_state=verification_state,
        setup_completed_at=setup_completed_at,
        suspended_at=suspended_at,
        suspension_reason="Suspended" if suspended_at is not None else None,
        created_at=now,
        updated_at=now,
    )


def _build_membership(
    *,
    role: OrganizationRole = OrganizationRole.OWNER,
    suspended_at: datetime | None = None,
):
    return SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        organization_id=uuid4(),
        user_id=uuid4(),
        role=role,
        suspended_at=suspended_at,
    )


def _build_service() -> WorkspaceService:
    service = WorkspaceService.__new__(WorkspaceService)
    service._session = SimpleNamespace(commit=AsyncMock())
    service._organizations = SimpleNamespace(
        get_by_id=AsyncMock(),
        get_membership=AsyncMock(),
        list_for_user=AsyncMock(return_value=[]),
    )
    service._invitations = SimpleNamespace(
        list_for_invitee=AsyncMock(return_value=[]),
    )
    service._users = SimpleNamespace(
        get_by_id=AsyncMock(),
    )
    return service


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role",
    [OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.MEMBER],
)
async def test_bootstrap_returns_ready_for_setup_complete_employer_membership(
    role: OrganizationRole,
) -> None:
    service = _build_service()
    now = datetime.now(tz=UTC)
    organization = _build_organization(
        organization_type=OrganizationType.EMPLOYER,
        verification_state=OrganizationVerificationState.VERIFIED,
        setup_completed_at=now,
    )
    user = _build_user(active_organization_id=organization.id)
    membership = _build_membership(role=role)
    membership.organization_id = organization.id
    membership.user_id = user.id

    service._users.get_by_id = AsyncMock(return_value=user)  # type: ignore[attr-defined]
    service._organizations.get_by_id = AsyncMock(return_value=organization)  # type: ignore[attr-defined]
    service._organizations.get_membership = AsyncMock(return_value=membership)  # type: ignore[attr-defined]

    response = await service.bootstrap(user.id)

    assert response.state == WorkspaceAccessState.READY
    assert response.setup_completed is True


@pytest.mark.asyncio
async def test_bootstrap_normalizes_stale_setup_incomplete_employer_to_ready() -> None:
    service = _build_service()
    now = datetime.now(tz=UTC)
    organization = _build_organization(
        organization_type=OrganizationType.EMPLOYER,
        verification_state=OrganizationVerificationState.SETUP_INCOMPLETE,
        setup_completed_at=now,
    )
    user = _build_user(active_organization_id=organization.id)
    membership = _build_membership(role=OrganizationRole.OWNER)
    membership.organization_id = organization.id
    membership.user_id = user.id

    service._users.get_by_id = AsyncMock(return_value=user)  # type: ignore[attr-defined]
    service._organizations.get_by_id = AsyncMock(return_value=organization)  # type: ignore[attr-defined]
    service._organizations.get_membership = AsyncMock(return_value=membership)  # type: ignore[attr-defined]

    response = await service.bootstrap(user.id)

    assert response.setup_completed is True
    assert response.state == WorkspaceAccessState.READY
    assert (
        response.organization_verification_state
        == OrganizationVerificationState.SETUP_INCOMPLETE
    )


@pytest.mark.asyncio
async def test_bootstrap_normalizes_stale_setup_incomplete_university_to_ready() -> None:
    service = _build_service()
    now = datetime.now(tz=UTC)
    organization = _build_organization(
        organization_type=OrganizationType.UNIVERSITY,
        verification_state=OrganizationVerificationState.SETUP_INCOMPLETE,
        setup_completed_at=now,
    )
    user = _build_user(active_organization_id=organization.id)
    membership = _build_membership(role=OrganizationRole.OWNER)
    membership.organization_id = organization.id
    membership.user_id = user.id

    service._users.get_by_id = AsyncMock(return_value=user)  # type: ignore[attr-defined]
    service._organizations.get_by_id = AsyncMock(return_value=organization)  # type: ignore[attr-defined]
    service._organizations.get_membership = AsyncMock(return_value=membership)  # type: ignore[attr-defined]

    response = await service.bootstrap(user.id)

    assert response.setup_completed is True
    assert response.state == WorkspaceAccessState.READY
    assert (
        response.organization_verification_state
        == OrganizationVerificationState.SETUP_INCOMPLETE
    )


def test_derive_state_returns_setup_incomplete_when_setup_not_finished() -> None:
    service = _build_service()
    organization = _build_organization(
        organization_type=OrganizationType.EMPLOYER,
        verification_state=OrganizationVerificationState.SETUP_INCOMPLETE,
        setup_completed_at=None,
    )
    membership = _build_membership()

    state = service._derive_state(organization, membership, None)

    assert state == WorkspaceAccessState.SETUP_INCOMPLETE


def test_derive_state_returns_no_org_without_membership_or_invitation() -> None:
    service = _build_service()

    state = service._derive_state(None, None, None)

    assert state == WorkspaceAccessState.NO_ORG


def test_derive_state_prioritizes_org_suspension_over_ready() -> None:
    service = _build_service()
    now = datetime.now(tz=UTC)
    organization = _build_organization(
        organization_type=OrganizationType.EMPLOYER,
        verification_state=OrganizationVerificationState.VERIFIED,
        setup_completed_at=now,
        suspended_at=now,
    )
    membership = _build_membership()

    state = service._derive_state(organization, membership, None)

    assert state == WorkspaceAccessState.ORG_SUSPENDED


def test_derive_state_prioritizes_membership_suspension_over_ready() -> None:
    service = _build_service()
    now = datetime.now(tz=UTC)
    organization = _build_organization(
        organization_type=OrganizationType.EMPLOYER,
        verification_state=OrganizationVerificationState.VERIFIED,
        setup_completed_at=now,
    )
    membership = _build_membership(suspended_at=now)

    state = service._derive_state(organization, membership, None)

    assert state == WorkspaceAccessState.MEMBERSHIP_SUSPENDED


def test_derive_state_keeps_university_verification_pending_gate() -> None:
    service = _build_service()
    now = datetime.now(tz=UTC)
    organization = _build_organization(
        organization_type=OrganizationType.UNIVERSITY,
        verification_state=OrganizationVerificationState.VERIFICATION_PENDING,
        setup_completed_at=now,
    )
    membership = _build_membership(role=OrganizationRole.ADMIN)

    state = service._derive_state(organization, membership, None)

    assert state == WorkspaceAccessState.VERIFICATION_PENDING
