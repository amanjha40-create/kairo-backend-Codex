"""Focused unit tests for workspace invitation acceptance lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.exceptions import ConflictError
from app.organization.enums import OrganizationInvitationStatus, OrganizationRole, OrganizationType
from app.services.workspace_service import WorkspaceService


def _build_user(email: str):
    return SimpleNamespace(
        id=uuid4(),
        email=email,
        full_name="Workspace User",
        role="user",
        active_organization_id=None,
    )


def _build_organization():
    now = datetime.now(tz=UTC)
    return SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        name="Kairo University",
        organization_type=OrganizationType.UNIVERSITY,
        website=None,
        industry=None,
        location=None,
        work_email="owner@kairo.example",
        domain="kairo.example",
        organization_size=None,
        hiring_volume=None,
        domain_verified_at=None,
        verification_state="verification_pending",
        setup_completed_at=now,
        suspended_at=None,
        suspension_reason=None,
        created_at=now,
        updated_at=now,
    )


def _build_invitation(*, organization, invited_by_user, invitee_email: str, role: OrganizationRole):
    now = datetime.now(tz=UTC)
    return SimpleNamespace(
        public_id=uuid4(),
        organization=organization,
        organization_id=organization.id,
        invitee_email=invitee_email,
        invitee_user_id=None,
        role=role,
        status=OrganizationInvitationStatus.PENDING,
        accepted_at=None,
        declined_at=None,
        cancelled_at=None,
        expires_at=now + timedelta(days=7),
        created_at=now,
        updated_at=now,
        invited_by_user=invited_by_user,
    )


def _build_membership(*, organization_id, user, role: OrganizationRole, suspended: bool = False):
    return SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        organization_id=organization_id,
        user_id=user.id,
        user=user,
        role=role,
        suspended_at=datetime.now(tz=UTC) if suspended else None,
    )


def _build_service() -> WorkspaceService:
    service = WorkspaceService.__new__(WorkspaceService)
    service._session = SimpleNamespace(commit=AsyncMock())
    service._organizations = SimpleNamespace(
        get_membership=AsyncMock(),
        add_member=AsyncMock(),
    )
    service._invitations = SimpleNamespace(
        get_by_public_id=AsyncMock(),
    )
    service._users = SimpleNamespace(
        get_by_id=AsyncMock(),
    )
    return service


@pytest.mark.asyncio
async def test_accept_invitation_creates_membership_when_missing() -> None:
    service = _build_service()
    user = _build_user("invitee@example.com")
    organization = _build_organization()
    inviter = _build_user("owner@example.com")
    invitation = _build_invitation(
        organization=organization,
        invited_by_user=inviter,
        invitee_email="invitee@example.com",
        role=OrganizationRole.ADMIN,
    )

    service._users.get_by_id = AsyncMock(return_value=user)  # type: ignore[attr-defined]
    service._invitations.get_by_public_id = AsyncMock(return_value=invitation)  # type: ignore[attr-defined]
    service._organizations.get_membership = AsyncMock(return_value=None)  # type: ignore[attr-defined]

    response = await service.accept_invitation(user.id, invitation.public_id)

    assert response.status == OrganizationInvitationStatus.ACCEPTED
    assert invitation.status == OrganizationInvitationStatus.ACCEPTED
    assert user.active_organization_id == organization.id
    service._organizations.add_member.assert_awaited_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_accept_invitation_rejects_suspended_membership() -> None:
    service = _build_service()
    user = _build_user("invitee@example.com")
    organization = _build_organization()
    inviter = _build_user("owner@example.com")
    invitation = _build_invitation(
        organization=organization,
        invited_by_user=inviter,
        invitee_email="invitee@example.com",
        role=OrganizationRole.REVIEWER,
    )
    membership = _build_membership(
        organization_id=organization.id,
        user=user,
        role=OrganizationRole.REVIEWER,
        suspended=True,
    )

    service._users.get_by_id = AsyncMock(return_value=user)  # type: ignore[attr-defined]
    service._invitations.get_by_public_id = AsyncMock(return_value=invitation)  # type: ignore[attr-defined]
    service._organizations.get_membership = AsyncMock(return_value=membership)  # type: ignore[attr-defined]

    with pytest.raises(ConflictError, match="Suspended memberships"):
        await service.accept_invitation(user.id, invitation.public_id)


@pytest.mark.asyncio
async def test_accept_invitation_rejects_role_mismatch() -> None:
    service = _build_service()
    user = _build_user("invitee@example.com")
    organization = _build_organization()
    inviter = _build_user("owner@example.com")
    invitation = _build_invitation(
        organization=organization,
        invited_by_user=inviter,
        invitee_email="invitee@example.com",
        role=OrganizationRole.ADMIN,
    )
    membership = _build_membership(
        organization_id=organization.id,
        user=user,
        role=OrganizationRole.MEMBER,
    )

    service._users.get_by_id = AsyncMock(return_value=user)  # type: ignore[attr-defined]
    service._invitations.get_by_public_id = AsyncMock(return_value=invitation)  # type: ignore[attr-defined]
    service._organizations.get_membership = AsyncMock(return_value=membership)  # type: ignore[attr-defined]

    with pytest.raises(ConflictError, match="does not match this invitation"):
        await service.accept_invitation(user.id, invitation.public_id)


@pytest.mark.asyncio
async def test_accept_invitation_allows_existing_same_role_membership() -> None:
    service = _build_service()
    user = _build_user("invitee@example.com")
    organization = _build_organization()
    inviter = _build_user("owner@example.com")
    invitation = _build_invitation(
        organization=organization,
        invited_by_user=inviter,
        invitee_email="invitee@example.com",
        role=OrganizationRole.ADMIN,
    )
    membership = _build_membership(
        organization_id=organization.id,
        user=user,
        role=OrganizationRole.ADMIN,
    )

    service._users.get_by_id = AsyncMock(return_value=user)  # type: ignore[attr-defined]
    service._invitations.get_by_public_id = AsyncMock(return_value=invitation)  # type: ignore[attr-defined]
    service._organizations.get_membership = AsyncMock(return_value=membership)  # type: ignore[attr-defined]

    response = await service.accept_invitation(user.id, invitation.public_id)

    assert response.status == OrganizationInvitationStatus.ACCEPTED
    service._organizations.add_member.assert_not_called()  # type: ignore[attr-defined]
