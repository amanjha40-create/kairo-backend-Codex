"""Real database transactions; synthetic identities and fake storage only."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError

from app.auth.passwords import hash_password
from app.config import get_settings
from app.db.session import async_session_factory
from app.exceptions import NotFoundError, ServiceUnavailableError, UnauthorizedError
from app.models import (
    AccountDeletion,
    AccountDeletionItem,
    Organization,
    OrganizationDeletionResolution,
    OrganizationInvitation,
    OrganizationMember,
    PassportShareLink,
    RefreshToken,
    User,
    UserSocialAccount,
)
from app.organization.enums import OrganizationInvitationStatus, OrganizationRole, OrganizationType
from app.schemas.account_deletion import AccountDeletionRequest
from app.services.account_deletion_purge import sweep_deletions
from app.services.account_deletion_service import AccountDeletionService
from app.services.organization_lifecycle import require_organization_open

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
PASSWORD = "SyntheticDeletionOnly123!"


class FakeRedis:
    async def delete(self, *keys):
        return len(keys)


class FakeStorage:
    def __init__(self, keys=()):
        self.keys = set(keys)
        self.deleted = []

    async def discover(self, bucket, prefix):
        return sorted(key for key in self.keys if key.startswith(prefix)), False

    async def purge(self, bucket, key):
        self.deleted.append(key)
        self.keys.discard(key)


@pytest.fixture
async def factory():
    uids, oids = [], []
    settings = get_settings().model_copy(
        update={
            "sqs_main_queue_url": None,
            "s3_documents_bucket": "synthetic-deletion-test",
            "s3_document_key_prefix": "test",
        }
    )

    async def create(*, successors=(), password=True, org=True, role="user"):
        now = datetime.now(UTC)
        async with async_session_factory() as session:
            owner = User(
                id=uuid4(),
                email=f"{uuid4()}@example.test",
                role=role,
                is_active=True,
                email_verified_at=now,
                password_hash=hash_password(PASSWORD) if password else None,
            )
            session.add(owner)
            await session.flush()
            uids.append(owner.id)
            organization = None
            successor_ids = []
            if org:
                organization = Organization(
                    id=uuid4(),
                    created_by_user_id=owner.id,
                    name="Synthetic closure fixture",
                    organization_type=OrganizationType.EMPLOYER,
                )
                session.add(organization)
                await session.flush()
                oids.append(organization.id)
                session.add(
                    OrganizationMember(
                        organization_id=organization.id,
                        user_id=owner.id,
                        role=OrganizationRole.OWNER,
                    )
                )
                for item in successors:
                    person = User(
                        id=uuid4(),
                        email=f"{uuid4()}@example.test",
                        role="user",
                        is_active=True,
                        email_verified_at=now,
                    )
                    session.add(person)
                    await session.flush()
                    uids.append(person.id)
                    successor_ids.append(person.id)
                    session.add(
                        OrganizationMember(
                            organization_id=organization.id,
                            user_id=person.id,
                            role=item.get("role", OrganizationRole.MEMBER),
                            suspended_at=now if item.get("suspended") else None,
                            created_at=now - timedelta(days=item.get("age", 0)),
                        )
                    )
                    await session.flush()
                    if item.get("inactive"):
                        person.is_active = False
                    if item.get("deleted"):
                        person.deleted_at = now
                        person.is_active = False
                owner.active_organization_id = organization.id
            family_id = uuid4()
            if not password:
                session.add(
                    UserSocialAccount(
                        user_id=owner.id,
                        provider="google",
                        provider_user_id=str(uuid4()),
                        provider_email=owner.email,
                    )
                )
            session.add(
                RefreshToken(
                    user_id=owner.id,
                    token_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
                    family_id=family_id,
                    expires_at=now + timedelta(days=1),
                )
            )
            session.add(
                PassportShareLink(
                    owner_user_id=owner.id,
                    token_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
                    permissions={"education": True},
                )
            )
            await session.commit()
            return SimpleNamespace(
                uid=owner.id,
                oid=organization.id if organization else None,
                successors=successor_ids,
                settings=settings,
                family_id=family_id,
            )

    yield create
    async with async_session_factory() as session:
        await session.execute(
            delete(OrganizationDeletionResolution).where(
                OrganizationDeletionResolution.organization_id.in_(oids)
            )
        )
        await session.execute(
            update(User).where(User.id.in_(uids)).values(active_organization_id=None)
        )
        await session.execute(delete(Organization).where(Organization.id.in_(oids)))
        ledgers = select(AccountDeletion.id).where(AccountDeletion.user_id.in_(uids))
        await session.execute(
            delete(AccountDeletionItem).where(AccountDeletionItem.deletion_id.in_(ledgers))
        )
        await session.execute(delete(AccountDeletion).where(AccountDeletion.user_id.in_(uids)))
        await session.execute(delete(User).where(User.id.in_(uids)))
        await session.commit()


async def erase(case, *, password=PASSWORD):
    async with async_session_factory() as session:
        await AccountDeletionService(session, case.settings, FakeRedis()).delete_candidate_account(
            case.uid,
            AccountDeletionRequest(confirm="DELETE", current_password=password),
        )


async def assert_erased(case):
    async with async_session_factory() as session:
        owner = await session.get(User, case.uid)
        assert owner.deleted_at is not None and not owner.is_active
        assert owner.active_organization_id is None and owner.password_hash is None
        for model, field in (
            (RefreshToken, RefreshToken.user_id),
            (PassportShareLink, PassportShareLink.owner_user_id),
            (OrganizationMember, OrganizationMember.user_id),
            (UserSocialAccount, UserSocialAccount.user_id),
        ):
            assert (
                await session.scalar(
                    select(func.count()).select_from(model).where(field == case.uid)
                )
                == 0
            )
        ledgers = (
            await session.scalars(
                select(AccountDeletion).where(AccountDeletion.user_id == case.uid)
            )
        ).all()
        assert len(ledgers) == 1
        return ledgers[0].id


@pytest.mark.parametrize("role", ["user", "hr", "admin", "institution"])
async def test_no_organization_self_service_roles(factory, role):
    case = await factory(org=False, role=role)
    await erase(case)
    await assert_erased(case)


@pytest.mark.parametrize("role", [OrganizationRole.ADMIN, OrganizationRole.MEMBER])
async def test_transfer_and_personal_erasure_are_one_transaction(factory, role):
    case = await factory(successors=({"role": role},))
    await erase(case)
    await assert_erased(case)
    async with async_session_factory() as session:
        organization = await session.get(Organization, case.oid)
        assert organization.closed_at is None
        successor = await session.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == case.oid,
                OrganizationMember.user_id == case.successors[0],
            )
        )
        assert successor.role == OrganizationRole.OWNER
        event = await session.scalar(
            select(OrganizationDeletionResolution).where(
                OrganizationDeletionResolution.organization_id == case.oid
            )
        )
        assert event.action == "transfer" and event.successor_user_id == case.successors[0]
        await require_organization_open(session, case.oid)


async def test_admin_wins_over_older_member(factory):
    case = await factory(successors=({"age": 100}, {"role": OrganizationRole.ADMIN}))
    await erase(case)
    async with async_session_factory() as session:
        owner = await session.scalar(
            select(OrganizationMember.user_id).where(
                OrganizationMember.organization_id == case.oid,
                OrganizationMember.role == OrganizationRole.OWNER,
            )
        )
        assert owner == case.successors[1]


@pytest.mark.parametrize("invalid", [{"inactive": True}, {"suspended": True}, {"deleted": True}])
async def test_ineligible_admin_is_not_successor(factory, invalid):
    case = await factory(successors=({"role": OrganizationRole.ADMIN, **invalid}, {}))
    await erase(case)
    async with async_session_factory() as session:
        event = await session.scalar(
            select(OrganizationDeletionResolution).where(
                OrganizationDeletionResolution.organization_id == case.oid
            )
        )
        assert event.successor_user_id == case.successors[1]


async def test_sole_owner_closes_and_revokes_pending_invite(factory):
    case = await factory()
    async with async_session_factory() as session:
        invite = OrganizationInvitation(
            organization_id=case.oid,
            invited_by_user_id=case.uid,
            invitee_email=f"{uuid4()}@example.test",
            role=OrganizationRole.ADMIN,
            token_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
        )
        session.add(invite)
        await session.commit()
        iid = invite.id
    await erase(case)
    await assert_erased(case)
    async with async_session_factory() as session:
        organization = await session.get(Organization, case.oid)
        assert organization.closed_at is not None and organization.suspended_at is not None
        assert organization.closure_deletion_id is not None
        invitation = await session.get(OrganizationInvitation, iid)
        assert invitation.status == OrganizationInvitationStatus.CANCELLED
        assert invitation.token_hash is None and invitation.token_revoked_at is not None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OrganizationMember)
                .where(OrganizationMember.organization_id == case.oid)
            )
            == 0
        )
        with pytest.raises(NotFoundError):
            await require_organization_open(session, case.oid)


async def test_only_inactive_members_closes_org(factory):
    case = await factory(successors=({"inactive": True},))
    await erase(case)
    async with async_session_factory() as session:
        assert (await session.get(Organization, case.oid)).closed_at is not None


async def test_creator_provenance_is_not_workspace_ownership(factory):
    admin = await factory(org=False, role="admin")
    directory = await factory()
    async with async_session_factory() as session:
        await session.execute(
            delete(OrganizationMember).where(OrganizationMember.organization_id == directory.oid)
        )
        await session.execute(
            update(Organization)
            .where(Organization.id == directory.oid)
            .values(created_by_user_id=admin.uid)
        )
        await session.commit()
    await erase(admin)
    async with async_session_factory() as session:
        assert (await session.get(Organization, directory.oid)).closed_at is None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OrganizationDeletionResolution)
                .where(OrganizationDeletionResolution.organization_id == directory.oid)
            )
            == 0
        )


async def test_non_owner_not_trapped_by_inactive_owner(factory):
    case = await factory(successors=({}, {}))
    departing = SimpleNamespace(**vars(case))
    departing.uid = case.successors[0]
    async with async_session_factory() as session:
        await session.execute(update(User).where(User.id == case.uid).values(is_active=False))
        await session.commit()
    await erase(departing, password=None)
    async with async_session_factory() as session:
        assert (await session.get(User, departing.uid)).deleted_at is not None
        assert (
            await session.scalar(
                select(OrganizationMember.role).where(
                    OrganizationMember.organization_id == case.oid,
                    OrganizationMember.user_id == case.successors[1],
                )
            )
            == OrganizationRole.OWNER
        )


async def test_stale_admin_cannot_suspend_transferred_last_owner(factory):
    from app.exceptions import ForbiddenError
    from app.schemas.organization import OrganizationMemberSuspendRequest
    from app.services.organization_service import OrganizationService

    case = await factory(
        successors=(
            {"role": OrganizationRole.ADMIN, "age": 10},
            {"role": OrganizationRole.ADMIN},
        )
    )
    async with async_session_factory() as stale:
        organization = await stale.get(Organization, case.oid)
        target = await stale.scalar(
            select(OrganizationMember).where(
                OrganizationMember.user_id == case.successors[0],
                OrganizationMember.organization_id == case.oid,
            )
        )
        assert target.role == OrganizationRole.ADMIN
        await erase(case)
        with pytest.raises(ForbiddenError):
            await OrganizationService(stale).suspend_member(
                case.successors[1],
                organization.public_id,
                target.public_id,
                OrganizationMemberSuspendRequest(reason="Synthetic test"),
            )
        await stale.rollback()
    async with async_session_factory() as session:
        member = await session.scalar(
            select(OrganizationMember).where(
                OrganizationMember.user_id == case.successors[0],
                OrganizationMember.organization_id == case.oid,
            )
        )
        assert member.role == OrganizationRole.OWNER and member.suspended_at is None


async def test_duplicate_concurrent_delete_has_one_ledger(factory):
    case = await factory()
    await asyncio.gather(erase(case), erase(case))
    await assert_erased(case)


@pytest.mark.parametrize("closure", [False, True])
async def test_resolution_failure_rolls_back_everything(factory, monkeypatch, closure):
    import app.services.account_deletion_service as module

    case = await factory(successors=() if closure else ({},))
    real = module.resolve_organizations_for_account_deletion

    async def fail_after_resolution(*args):
        await real(*args)
        raise RuntimeError("synthetic fault after organization resolution")

    monkeypatch.setattr(module, "resolve_organizations_for_account_deletion", fail_after_resolution)
    with pytest.raises(ServiceUnavailableError):
        await erase(case)
    async with async_session_factory() as session:
        assert (await session.get(User, case.uid)).deleted_at is None
        assert (await session.get(Organization, case.oid)).closed_at is None
        assert (
            await session.scalar(
                select(OrganizationMember.role).where(
                    OrganizationMember.organization_id == case.oid,
                    OrganizationMember.user_id == case.uid,
                )
            )
            == OrganizationRole.OWNER
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AccountDeletion)
                .where(AccountDeletion.user_id == case.uid)
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(RefreshToken)
                .where(RefreshToken.user_id == case.uid)
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(PassportShareLink)
                .where(PassportShareLink.owner_user_id == case.uid)
            )
            == 1
        )


async def test_wrong_password_has_no_organization_side_effect(factory):
    case = await factory(successors=({},))
    with pytest.raises(UnauthorizedError):
        await erase(case, password="WrongPassword123!")
    async with async_session_factory() as session:
        assert (await session.get(User, case.uid)).deleted_at is None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AccountDeletion)
                .where(AccountDeletion.user_id == case.uid)
            )
            == 0
        )


async def test_social_passwordless_contract_and_duplicate_are_idempotent(factory):
    case = await factory(password=False)
    await erase(case, password=None)
    first = await assert_erased(case)
    await erase(case, password=None)
    assert await assert_erased(case) == first
    async with async_session_factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OrganizationDeletionResolution)
                .where(OrganizationDeletionResolution.deletion_id == first)
            )
            == 1
        )


async def test_sweeper_completes_closed_org_logo_without_other_org_assets(factory):
    case = await factory()
    other = await factory()
    key = f"test/organizations/{case.oid}/logo/synthetic.png"
    other_key = f"test/organizations/{other.oid}/logo/untouched.png"
    storage = FakeStorage((key, other_key))
    await erase(case)
    did = await assert_erased(case)
    later = datetime.now(UTC) + timedelta(hours=1)
    for _ in range(2):
        async with async_session_factory() as session:
            result = await sweep_deletions(
                session,
                case.settings,
                FakeRedis(),
                storage=storage,
                deletion_id=did,
                now=later,
            )
        later += timedelta(minutes=5)
    assert result["pending"] == 0 and result["review"] == 0
    assert storage.keys == {other_key}
    async with async_session_factory() as session:
        request = await session.get(AccountDeletion, did)
        assert request.status == "complete" and request.retry_count == 0
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AccountDeletion)
                .where(
                    AccountDeletion.id == did,
                    AccountDeletion.status != "complete",
                    AccountDeletion.next_attempt_at <= later,
                )
            )
            == 0
        )


async def test_closed_organization_cannot_be_reopened_or_rejoined(factory):
    case = await factory()
    other = await factory(org=False)
    await erase(case)
    async with async_session_factory() as session:
        with pytest.raises(DBAPIError):
            await session.execute(
                update(Organization)
                .where(Organization.id == case.oid)
                .values(closed_at=None, closure_deletion_id=None, suspended_at=None)
            )
        await session.rollback()
        session.add(
            OrganizationMember(
                organization_id=case.oid, user_id=other.uid, role=OrganizationRole.OWNER
            )
        )
        with pytest.raises(DBAPIError):
            await session.flush()
        await session.rollback()


async def test_closed_org_signed_trust_invitation_fails_closed(factory):
    from app.models import TrustInvitation
    from app.services.trust_invitation_service import TrustInvitationService
    from app.trust_invitations.enums import TrustInvitationStatus

    case = await factory()
    async with async_session_factory() as session:
        invitation = TrustInvitation(
            organization_id=case.oid,
            created_by_user_id=case.uid,
            subject_name="Synthetic",
            subject_email="synthetic@example.test",
            token_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
            status=TrustInvitationStatus.ACCEPTED,
            accepted_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        session.add(invitation)
        await session.commit()
        token = TrustInvitationService(session, case.settings)._build_signed_token(
            invitation.public_id
        )
    await erase(case)
    async with async_session_factory() as session:
        with pytest.raises(NotFoundError):
            await TrustInvitationService(session, case.settings)._resolve_token_for_accept(token)


async def test_forged_org_cleanup_scope_is_rejected(factory):
    from app.services.account_deletion_inventory import identity

    case = await factory(org=False)
    other = await factory()
    await erase(case)
    did = await assert_erased(case)
    scope = f"test/organizations/{other.oid}/logo/"
    storage = FakeStorage((scope + "preserve.png",))
    now = datetime.now(UTC) + timedelta(hours=1)
    async with async_session_factory() as session:
        session.add(
            AccountDeletionItem(
                deletion_id=did,
                identity_hash=identity("namespace", scope),
                kind="namespace",
                source_type="closed_org_logo",
                source_id=other.oid,
                scope_prefix=scope,
                object_key=scope,
                status="pending",
                next_attempt_at=now,
            )
        )
        await session.commit()
    async with async_session_factory() as session:
        result = await sweep_deletions(
            session,
            case.settings,
            FakeRedis(),
            deletion_id=did,
            now=now,
            storage=storage,
        )
    assert result["review"] == 1
    assert storage.keys == {scope + "preserve.png"}
    assert not any(key.startswith(scope) for key in storage.deleted)


async def test_successor_locked_for_deletion_aborts_without_partial_transfer(factory):
    case = await factory(successors=({},))
    async with async_session_factory() as other_session:
        await other_session.scalar(
            select(User).where(User.id == case.successors[0]).with_for_update()
        )
        with pytest.raises(ServiceUnavailableError):
            await asyncio.wait_for(erase(case), timeout=5)
        await other_session.rollback()
    async with async_session_factory() as session:
        assert (await session.get(User, case.uid)).deleted_at is None
        assert (
            await session.scalar(
                select(OrganizationMember.role).where(
                    OrganizationMember.organization_id == case.oid,
                    OrganizationMember.user_id == case.uid,
                )
            )
            == OrganizationRole.OWNER
        )


@pytest.mark.parametrize("successors", [(), ({"role": OrganizationRole.ADMIN},), ({},)])
async def test_mobile_facing_route_performs_normal_delete(factory, successors):
    from httpx import ASGITransport, AsyncClient

    from app.api.dependencies.services import get_account_deletion_service
    from app.auth.tokens import create_access_token
    from app.db.session import get_session
    from app.main import app

    case = await factory(successors=successors)
    async with async_session_factory() as session:

        async def test_session():
            yield session

        async def service():
            return AccountDeletionService(session, case.settings, FakeRedis())

        before = dict(app.dependency_overrides)
        app.dependency_overrides[get_session] = test_session
        app.dependency_overrides[get_account_deletion_service] = service
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.request(
                    "DELETE",
                    "/api/v1/users/me",
                    json={
                        "confirm": "DELETE",
                        "current_password": PASSWORD,
                    },
                    headers={
                        "Authorization": "Bearer "
                        + create_access_token(
                            case.settings,
                            subject=case.uid,
                            role="user",
                            extra_claims={"sid": str(case.family_id)},
                        )
                    },
                )
            assert response.status_code == 204, response.text
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(before)
    await assert_erased(case)
