"""Real two-session races; database blocking, not sleeps, establishes ordering."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from app.config import get_settings
from app.db.session import async_session_factory
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.organization import Organization
from app.models.organization_invitation import OrganizationInvitation
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.organization.enums import OrganizationRole, OrganizationType
from app.repositories.organization_invitation import OrganizationInvitationRepository
from app.schemas.admin_operations import (
    AdminFirstHRInvitationRequest,
    AdminOrganizationCreateRequest,
)
from app.schemas.organization import (
    OrganizationInvitationCreateRequest,
    OrganizationMemberCreateRequest,
)
from app.services.admin_operations_service import AdminOperationsService
from app.services.organization_service import OrganizationService
from app.services.workspace_service import WorkspaceService


class MailSink:
    def __init__(self):
        self.calls = []

    async def queue_template_email(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(status="queued")


def token(mail):
    return parse_qs(urlparse(mail.calls[-1]["template_data"]["invitation_url"]).query)["token"][0]


async def fixture(first_hr):
    mail = MailSink()
    async with async_session_factory() as db:
        actor = User(
            email=f"race-admin-{uuid4()}@example.com",
            full_name="Synthetic Admin",
            role="admin",
            is_active=True,
        )
        invitee = User(
            email=f"race-hr-{uuid4()}@example.com",
            full_name="Synthetic HR",
            role="hr",
            is_active=True,
        )
        db.add_all([actor, invitee])
        await db.commit()
        admin = AdminOperationsService(db, get_settings(), email_delivery=mail)
        created = await admin.create_organization(
            actor.id,
            AdminOrganizationCreateRequest(
                name=f"Synthetic race {uuid4()}",
                organization_type=OrganizationType.EMPLOYER,
                idempotency_key=uuid4(),
            ),
        )
        org = await db.scalar(
            select(Organization).where(Organization.public_id == created.organization_public_id)
        )
        if first_hr:
            invitation = await admin.invite_first_hr(
                actor.id,
                org.public_id,
                AdminFirstHRInvitationRequest(
                    full_name=invitee.full_name, email=invitee.email, role=OrganizationRole.OWNER
                ),
            )
            invitation_id = invitation.invitation_public_id
        else:
            db.add(
                OrganizationMember(
                    organization_id=org.id, user_id=actor.id, role=OrganizationRole.OWNER
                )
            )
            await db.commit()
            invitation = await OrganizationService(
                db, settings=get_settings(), email_delivery=mail
            ).create_invitation(
                actor.id,
                org.public_id,
                OrganizationInvitationCreateRequest(
                    invitee_email=invitee.email, role=OrganizationRole.MEMBER
                ),
            )
            invitation_id = invitation.public_id
        return SimpleNamespace(
            org=org.id,
            org_public=org.public_id,
            actor=actor.id,
            invitee=invitee.id,
            email=invitee.email,
            name=invitee.full_name,
            invitation=invitation_id,
            raw=token(mail),
            mail=mail,
        )


async def operate(db, case, operation):
    if operation == "accept":
        return await WorkspaceService(db).accept_team_invitation(case.invitee, case.raw)
    if operation == "suspend":
        org = await db.scalar(
            select(Organization)
            .where(Organization.id == case.org)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        org.suspended_at = datetime.now(UTC)
        await db.commit()
        return "suspended"
    if operation == "admin_resend":
        return await AdminOperationsService(
            db, get_settings(), email_delivery=case.mail
        ).invite_first_hr(
            case.actor,
            case.org_public,
            AdminFirstHRInvitationRequest(
                full_name=case.name, email=case.email, role=OrganizationRole.OWNER
            ),
            resend_invitation_public_id=case.invitation,
        )
    service = OrganizationService(db, settings=get_settings(), email_delivery=case.mail)
    method = service.cancel_invitation if operation == "revoke" else service.resend_invitation
    return await method(case.actor, case.org_public, case.invitation)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "first,second,first_hr,second_ok,members",
    [
        ("accept", "accept", False, False, 1),
        ("accept", "revoke", False, False, 1),
        ("revoke", "accept", False, False, 0),
        ("accept", "resend", False, False, 1),
        ("resend", "accept", False, False, 0),
        ("resend", "revoke", False, True, 0),
        ("revoke", "resend", False, False, 0),
        ("suspend", "accept", True, False, 0),
        ("accept", "suspend", True, True, 1),
        ("admin_resend", "accept", True, False, 0),
        ("accept", "admin_resend", True, False, 1),
        ("suspend", "admin_resend", True, False, 0),
        ("admin_resend", "suspend", True, True, 0),
    ],
)
async def test_team_races(first, second, first_hr, second_ok, members):
    case = await fixture(first_hr)
    async with (
        async_session_factory() as winner,
        async_session_factory() as loser,
        async_session_factory() as observer,
    ):
        for db in (winner, loser):
            await db.execute(text("SET LOCAL lock_timeout = '5s'"))
            await db.execute(text("SET LOCAL statement_timeout = '8s'"))
        # Deliberately preload stale ORM state before the winner rotates/revokes.
        stale = await OrganizationInvitationRepository(loser).get_by_public_id(case.invitation)
        assert stale.status == "pending"
        loser_pid = await loser.scalar(text("SELECT pg_backend_pid()"))
        winner_pid = await winner.scalar(text("SELECT pg_backend_pid()"))
        await winner.scalar(
            select(Organization).where(Organization.id == case.org).with_for_update()
        )
        waiter = asyncio.create_task(operate(loser, case, second))
        try:
            async with asyncio.timeout(4):
                while True:
                    blockers = await observer.scalar(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": loser_pid}
                    )
                    if winner_pid in blockers:
                        break
                    assert not waiter.done(), "Contender did not honor organization-first locking"
                    await asyncio.sleep(0)
            await operate(winner, case, first)
            if second_ok:
                await asyncio.wait_for(waiter, 5)
            else:
                with pytest.raises((ConflictError, ForbiddenError, NotFoundError)):
                    await asyncio.wait_for(waiter, 5)
            await loser.rollback()
        finally:
            if not waiter.done():
                waiter.cancel()
                await asyncio.gather(waiter, return_exceptions=True)
            await winner.rollback()
        await observer.rollback()
        count = await observer.scalar(
            select(func.count())
            .select_from(OrganizationMember)
            .where(
                OrganizationMember.organization_id == case.org,
                OrganizationMember.user_id == case.invitee,
            )
        )
        assert count == members
        row = await OrganizationInvitationRepository(observer).get_by_public_id(case.invitation)
        if members:
            assert row.status == "accepted" and row.token_used_at is not None
        elif "revoke" in (first, second):
            assert row.status == "cancelled" and row.token_revoked_at is not None
        with pytest.raises((ConflictError, ForbiddenError, NotFoundError)):
            await WorkspaceService(observer).accept_team_invitation(case.invitee, case.raw)
        await observer.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_direct_adds_lock_parent_before_membership_fk_and_expiry(monkeypatch):
    case = await fixture(False)
    async with async_session_factory() as setup:
        other = User(
            email=f"race-other-{uuid4()}@example.com",
            full_name="Synthetic Other",
            role="hr",
            is_active=True,
        )
        setup.add(other)
        await setup.commit()
        invite = await OrganizationService(
            setup, settings=get_settings(), email_delivery=case.mail
        ).create_invitation(
            case.actor,
            case.org_public,
            OrganizationInvitationCreateRequest(
                invitee_email=other.email, role=OrganizationRole.MEMBER
            ),
        )
        expired = list(
            (
                await setup.scalars(
                    select(OrganizationInvitation).where(
                        OrganizationInvitation.public_id.in_([case.invitation, invite.public_id])
                    )
                )
            ).all()
        )
        for row in expired:
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await setup.commit()
        other_email, other_id = other.email, other.id
    async with (
        async_session_factory() as winner,
        async_session_factory() as loser,
        async_session_factory() as observer,
    ):
        await winner.scalar(
            select(Organization).where(Organization.id == case.org).with_for_update()
        )
        winner_pid = await winner.scalar(text("SELECT pg_backend_pid()"))
        loser_pid = await loser.scalar(text("SELECT pg_backend_pid()"))
        await loser.execute(text("SET LOCAL lock_timeout = '5s'"))
        service = OrganizationService(loser)
        entered_insert = asyncio.Event()
        original_add = service._organizations.add_member

        async def monitored_add(row):
            entered_insert.set()
            return await original_add(row)

        monkeypatch.setattr(service._organizations, "add_member", monitored_add)
        waiter = asyncio.create_task(
            service.add_member(
                case.actor,
                case.org_public,
                OrganizationMemberCreateRequest(email=other_email, role=OrganizationRole.MEMBER),
            )
        )
        try:
            async with asyncio.timeout(4):
                while winner_pid not in await observer.scalar(
                    text("SELECT pg_blocking_pids(:pid)"), {"pid": loser_pid}
                ):
                    assert not waiter.done()
                    await asyncio.sleep(0)
            assert not entered_insert.is_set(), "Membership FK lock must not precede parent lock"
            await OrganizationService(winner).add_member(
                case.actor,
                case.org_public,
                OrganizationMemberCreateRequest(email=case.email, role=OrganizationRole.MEMBER),
            )
            await asyncio.wait_for(waiter, 5)
        finally:
            if not waiter.done():
                waiter.cancel()
                await asyncio.gather(waiter, return_exceptions=True)
            await loser.rollback()
            await winner.rollback()
        await observer.rollback()
        assert (
            await observer.scalar(
                select(func.count())
                .select_from(OrganizationMember)
                .where(
                    OrganizationMember.organization_id == case.org,
                    OrganizationMember.user_id.in_([case.invitee, other_id]),
                )
            )
            == 2
        )
