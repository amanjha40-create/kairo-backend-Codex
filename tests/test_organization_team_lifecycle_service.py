"""Focused unit tests for organization team invitation and lifecycle rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.exceptions import ConflictError, ForbiddenError
from app.organization.enums import OrganizationInvitationStatus, OrganizationRole, OrganizationType
from app.schemas.organization import (
    OrganizationInvitationCreateRequest,
    OrganizationMemberSuspendRequest,
)
from app.services.organization_service import INVITATION_TTL, OrganizationService


def _build_user(*, email: str = "member@example.com", active_organization_id=None):
    return SimpleNamespace(
        id=uuid4(),
        email=email,
        full_name="Member User",
        active_organization_id=active_organization_id,
    )


def _build_organization():
    return SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        name="Kairo University",
        organization_type=OrganizationType.UNIVERSITY,
    )


def _build_membership(*, user, organization_id, role: OrganizationRole, suspended: bool = False):
    return SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        organization_id=organization_id,
        user_id=user.id,
        user=user,
        role=role,
        suspended_at=datetime.now(tz=UTC) if suspended else None,
        suspension_reason="Suspended" if suspended else None,
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )


def _build_invitation(*, organization, invited_by_user, role: OrganizationRole, invitee_email: str):
    now = datetime.now(tz=UTC)
    return SimpleNamespace(
        id=uuid4(),
        public_id=uuid4(),
        organization=organization,
        organization_id=organization.id,
        invited_by_user=invited_by_user,
        invited_by_user_id=invited_by_user.id,
        invitee_user_id=None,
        invitee_email=invitee_email,
        role=role,
        status=OrganizationInvitationStatus.PENDING,
        expires_at=now + INVITATION_TTL,
        accepted_at=None,
        declined_at=None,
        cancelled_at=None,
        created_at=now,
        updated_at=now,
    )


def _build_service() -> OrganizationService:
    service = OrganizationService.__new__(OrganizationService)
    service._session = SimpleNamespace(commit=AsyncMock(), flush=AsyncMock())
    service._organizations = SimpleNamespace(
        get_by_public_id=AsyncMock(),
        get_membership=AsyncMock(),
        add_member=AsyncMock(),
        get_member_by_public_id=AsyncMock(),
        count_active_owners=AsyncMock(return_value=1),
        delete_member=AsyncMock(),
        list_for_user=AsyncMock(return_value=[]),
    )
    service._invitations = SimpleNamespace(
        list_active_pending_for_organization_email=AsyncMock(return_value=[]),
        create=AsyncMock(),
        get_by_public_id_for_organization=AsyncMock(),
    )
    service._users = SimpleNamespace(get_by_email=AsyncMock(), get_by_id=AsyncMock())
    return service


@pytest.mark.asyncio
async def test_create_invitation_normalizes_email_and_binds_existing_user() -> None:
    service = _build_service()
    organization = _build_organization()
    actor = _build_user(email="owner@example.com")
    actor_membership = _build_membership(
        user=actor,
        organization_id=organization.id,
        role=OrganizationRole.ADMIN,
    )
    existing_user = _build_user(email="invitee@example.com")
    created_invitation = _build_invitation(
        organization=organization,
        invited_by_user=actor,
        role=OrganizationRole.ADMIN,
        invitee_email="invitee@example.com",
    )
    created_invitation.invitee_user_id = existing_user.id

    async def _create(invitation):  # noqa: ANN001
        invitation.public_id = created_invitation.public_id
        return invitation

    service._organizations.get_by_public_id = AsyncMock(return_value=organization)  # type: ignore[attr-defined]
    service._organizations.get_membership = AsyncMock(side_effect=[actor_membership, None])  # type: ignore[attr-defined]
    service._users.get_by_email = AsyncMock(return_value=existing_user)  # type: ignore[attr-defined]
    service._invitations.create = AsyncMock(side_effect=_create)  # type: ignore[attr-defined]
    service._invitations.get_by_public_id_for_organization = AsyncMock(  # type: ignore[attr-defined]
        return_value=created_invitation
    )

    result = await service.create_invitation(
        actor.id,
        organization.public_id,
        OrganizationInvitationCreateRequest(invitee_email=" Invitee@Example.com ", role="admin"),
    )

    assert result.invitee_email == "invitee@example.com"
    created_arg = service._invitations.create.await_args.args[0]  # type: ignore[attr-defined]
    assert created_arg.invitee_email == "invitee@example.com"
    assert created_arg.invitee_user_id == existing_user.id


@pytest.mark.asyncio
async def test_create_invitation_rejects_duplicate_pending_invitation() -> None:
    service = _build_service()
    organization = _build_organization()
    actor = _build_user(email="owner@example.com")
    actor_membership = _build_membership(
        user=actor,
        organization_id=organization.id,
        role=OrganizationRole.OWNER,
    )
    pending = _build_invitation(
        organization=organization,
        invited_by_user=actor,
        role=OrganizationRole.REVIEWER,
        invitee_email="invitee@example.com",
    )

    service._organizations.get_by_public_id = AsyncMock(return_value=organization)  # type: ignore[attr-defined]
    service._organizations.get_membership = AsyncMock(return_value=actor_membership)  # type: ignore[attr-defined]
    service._users.get_by_email = AsyncMock(return_value=None)  # type: ignore[attr-defined]
    service._invitations.list_active_pending_for_organization_email = AsyncMock(  # type: ignore[attr-defined]
        return_value=[pending]
    )

    with pytest.raises(ConflictError, match="active invitation already exists"):
        await service.create_invitation(
            actor.id,
            organization.public_id,
            OrganizationInvitationCreateRequest(
                invitee_email="invitee@example.com",
                role="reviewer",
            ),
        )


@pytest.mark.asyncio
async def test_suspend_member_blocks_last_active_owner() -> None:
    service = _build_service()
    organization = _build_organization()
    actor = _build_user(email="owner@example.com", active_organization_id=organization.id)
    target = _build_user(email="co-owner@example.com", active_organization_id=organization.id)
    actor_membership = _build_membership(
        user=actor,
        organization_id=organization.id,
        role=OrganizationRole.OWNER,
    )
    target_membership = _build_membership(
        user=target,
        organization_id=organization.id,
        role=OrganizationRole.OWNER,
    )

    service._organizations.get_by_public_id = AsyncMock(return_value=organization)  # type: ignore[attr-defined]
    service._organizations.get_membership = AsyncMock(return_value=actor_membership)  # type: ignore[attr-defined]
    service._organizations.get_member_by_public_id = AsyncMock(return_value=target_membership)  # type: ignore[attr-defined]
    service._organizations.count_active_owners = AsyncMock(return_value=1)  # type: ignore[attr-defined]

    with pytest.raises(ConflictError, match="last active owner"):
        await service.suspend_member(
            actor.id,
            organization.public_id,
            target_membership.public_id,
            OrganizationMemberSuspendRequest(reason="Left"),
        )


@pytest.mark.asyncio
async def test_admin_cannot_remove_owner_membership() -> None:
    service = _build_service()
    organization = _build_organization()
    actor = _build_user(email="admin@example.com")
    target = _build_user(email="owner@example.com")
    actor_membership = _build_membership(
        user=actor,
        organization_id=organization.id,
        role=OrganizationRole.ADMIN,
    )
    target_membership = _build_membership(
        user=target,
        organization_id=organization.id,
        role=OrganizationRole.OWNER,
    )

    service._organizations.get_by_public_id = AsyncMock(return_value=organization)  # type: ignore[attr-defined]
    service._organizations.get_membership = AsyncMock(return_value=actor_membership)  # type: ignore[attr-defined]
    service._organizations.get_member_by_public_id = AsyncMock(return_value=target_membership)  # type: ignore[attr-defined]

    with pytest.raises(ForbiddenError, match="Admins cannot affect owner memberships"):
        await service.remove_member(actor.id, organization.public_id, target_membership.public_id)


@pytest.mark.asyncio
async def test_transfer_ownership_is_atomic() -> None:
    service = _build_service()
    organization = _build_organization()
    actor = _build_user(email="owner@example.com")
    target = _build_user(email="reviewer@example.com")
    actor_membership = _build_membership(
        user=actor,
        organization_id=organization.id,
        role=OrganizationRole.OWNER,
    )
    target_membership = _build_membership(
        user=target,
        organization_id=organization.id,
        role=OrganizationRole.REVIEWER,
    )

    service._organizations.get_by_public_id = AsyncMock(return_value=organization)  # type: ignore[attr-defined]
    service._organizations.get_membership = AsyncMock(return_value=actor_membership)  # type: ignore[attr-defined]
    service._organizations.get_member_by_public_id = AsyncMock(return_value=target_membership)  # type: ignore[attr-defined]

    response = await service.transfer_ownership(
        actor.id,
        organization.public_id,
        target_membership.public_id,
    )

    assert actor_membership.role == OrganizationRole.ADMIN
    assert target_membership.role == OrganizationRole.OWNER
    assert response.new_owner_member_public_id == target_membership.public_id
    service._session.commit.assert_awaited_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_remove_member_reassigns_active_organization() -> None:
    service = _build_service()
    organization = _build_organization()
    fallback_organization = _build_organization()
    actor = _build_user(email="owner@example.com")
    target = _build_user(email="member@example.com", active_organization_id=organization.id)
    actor_membership = _build_membership(
        user=actor,
        organization_id=organization.id,
        role=OrganizationRole.OWNER,
    )
    target_membership = _build_membership(
        user=target,
        organization_id=organization.id,
        role=OrganizationRole.REVIEWER,
    )
    fallback_membership = _build_membership(
        user=target,
        organization_id=fallback_organization.id,
        role=OrganizationRole.REVIEWER,
    )

    service._organizations.get_by_public_id = AsyncMock(return_value=organization)  # type: ignore[attr-defined]
    service._organizations.get_membership = AsyncMock(return_value=actor_membership)  # type: ignore[attr-defined]
    service._organizations.get_member_by_public_id = AsyncMock(return_value=target_membership)  # type: ignore[attr-defined]
    service._organizations.list_for_user = AsyncMock(  # type: ignore[attr-defined]
        return_value=[
            (organization, target_membership),
            (fallback_organization, fallback_membership),
        ]
    )

    await service.remove_member(actor.id, organization.public_id, target_membership.public_id)

    assert target.active_organization_id == fallback_organization.id
    service._organizations.delete_member.assert_awaited_once_with(target_membership)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_resend_invitation_extends_expiry() -> None:
    service = _build_service()
    organization = _build_organization()
    actor = _build_user(email="owner@example.com")
    actor_membership = _build_membership(
        user=actor,
        organization_id=organization.id,
        role=OrganizationRole.ADMIN,
    )
    invitation = _build_invitation(
        organization=organization,
        invited_by_user=actor,
        role=OrganizationRole.REVIEWER,
        invitee_email="invitee@example.com",
    )
    original_expiry = invitation.expires_at

    service._organizations.get_by_public_id = AsyncMock(return_value=organization)  # type: ignore[attr-defined]
    service._organizations.get_membership = AsyncMock(return_value=actor_membership)  # type: ignore[attr-defined]
    service._invitations.get_by_public_id_for_organization = AsyncMock(return_value=invitation)  # type: ignore[attr-defined]
    service._users.get_by_email = AsyncMock(return_value=None)  # type: ignore[attr-defined]

    result = await service.resend_invitation(actor.id, organization.public_id, invitation.public_id)

    assert result.status == OrganizationInvitationStatus.PENDING
    assert invitation.expires_at is not None
    assert invitation.expires_at >= original_expiry
    assert invitation.expires_at <= datetime.now(tz=UTC) + INVITATION_TTL + timedelta(seconds=1)
