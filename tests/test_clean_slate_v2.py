from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update

from app.config import get_settings
from app.core.constants import Role
from app.db.session import async_session_factory
from app.models import (
    AccountDeletion,
    AccountDeletionItem,
    Organization,
    OrganizationDeletionResolution,
    OrganizationMember,
    OrganizationPerson,
    TrustSafetyInvestigation,
    User,
)
from app.ops.clean_slate import load_allowlist
from app.organization.enums import OrganizationRole, OrganizationType
from app.organization_people.enums import OrganizationPersonVerificationStatusSummary
from app.services.account_deletion_purge import permitted_scope
from app.services.clean_slate_orchestrator import (
    CleanSlateAllowlist,
    CleanSlateOrchestrator,
    CleanSlateSafetyError,
)
from app.services.clean_slate_synthetic_organization import (
    SyntheticOrganizationPurgeTarget,
)


class FakeRedis:
    async def delete(self, *keys):  # noqa: ANN002, ANN201
        return len(keys)


async def _empty_keys(_bucket, _scopes):  # noqa: ANN001, ANN202
    return set()


async def _user(session, role: str) -> User:  # noqa: ANN001
    row = User(
        id=uuid4(),
        email=f"clean-slate-v2-{uuid4()}@example.test",
        role=role,
        is_active=True,
        email_verified_at=datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    return row


def _allowlist(
    *,
    candidates: frozenset[UUID] = frozenset(),
    admins: frozenset[UUID] = frozenset(),
    protected: frozenset[UUID] = frozenset(),
    purges: tuple[SyntheticOrganizationPurgeTarget, ...] = (),
    preserves: frozenset[UUID] = frozenset(),
) -> CleanSlateAllowlist:
    return CleanSlateAllowlist(
        schema_version=2,
        environment="test",
        approved_user_ids=candidates,
        approved_pending_signup_ids=frozenset(),
        approved_organization_ids=frozenset(),
        approved_storage_object_ids=frozenset(),
        protected_user_ids=protected,
        approved_admin_user_ids=admins,
        organization_purge_targets=purges,
        organization_preserve_ids=preserves,
        retention_records=("user_tombstones", "organization_audit"),
    )


def test_v2_manifest_parser_binds_explicit_destructive_scopes() -> None:
    candidate_id = uuid4()
    admin_id = uuid4()
    protected_id = uuid4()
    purge_id = uuid4()
    preserve_id = uuid4()
    payload = {
        "schema_version": 2,
        "environment": "production",
        "user_deletion_ids": [str(candidate_id)],
        "admin_deletion_ids": [str(admin_id)],
        "pending_signup_deletion_ids": [],
        "organization_purge_targets": [
            {"organization_id": str(purge_id), "expected_person_count": 100}
        ],
        "organization_preserve_ids": [str(preserve_id)],
        "storage_deletion_object_ids": ["a" * 64],
        "protected_user_ids": [str(protected_id)],
        "retention_records": ["user_tombstones"],
        "backup_evidence": None,
    }
    parsed = load_allowlist(json.dumps(payload).encode())
    assert parsed.schema_version == 2
    assert parsed.approved_user_ids == frozenset({candidate_id})
    assert parsed.approved_admin_user_ids == frozenset({admin_id})
    assert parsed.organization_purge_targets[0].organization_id == purge_id
    assert parsed.organization_purge_targets[0].expected_person_count == 100
    assert parsed.organization_preserve_ids == frozenset({preserve_id})


@pytest.mark.asyncio
@pytest.mark.integration
async def test_v2_candidate_cleanup_succeeds() -> None:
    user_ids: list[UUID] = []
    try:
        async with async_session_factory() as session:
            candidate = await _user(session, Role.USER.value)
            superadmin = await _user(session, Role.SUPERADMIN.value)
            user_ids.extend((candidate.id, superadmin.id))
            await session.commit()
            allowlist = _allowlist(
                candidates=frozenset({candidate.id}),
                protected=frozenset({superadmin.id}),
            )
            orchestrator = _orchestrator(session)
            await orchestrator.plan(allowlist, require_storage_allowlist=True)
            result = await orchestrator.execute(
                allowlist,
                confirmation="EXECUTE STAGING CLEAN SLATE",
                backup_verified=True,
                health_check=_health,
                progress=lambda _event: None,
            )
            assert len(result) == 1
        async with async_session_factory() as session:
            candidate = await session.get(User, user_ids[0])
            superadmin = await session.get(User, user_ids[1])
            assert candidate is not None and candidate.deleted_at is not None
            assert superadmin is not None and superadmin.deleted_at is None
    finally:
        await _cleanup(user_ids, [])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_v2_admin_purges_100_people_and_preserves_creator_org_idempotently() -> None:
    user_ids: list[UUID] = []
    organization_ids: list[UUID] = []
    try:
        async with async_session_factory() as session:
            superadmin = await _user(session, Role.SUPERADMIN.value)
            admin = await _user(session, Role.ADMIN.value)
            user_ids.extend((superadmin.id, admin.id))
            preserved = Organization(
                id=uuid4(),
                created_by_user_id=admin.id,
                name="Preserved Kairo-like organization",
                organization_type=OrganizationType.EMPLOYER,
            )
            synthetic = Organization(
                id=uuid4(),
                created_by_user_id=admin.id,
                name="Synthetic QA organization",
                organization_type=OrganizationType.UNIVERSITY,
            )
            session.add_all((preserved, synthetic))
            await session.flush()
            organization_ids.extend((preserved.id, synthetic.id))
            session.add_all(
                (
                    OrganizationMember(
                        organization_id=preserved.id,
                        user_id=superadmin.id,
                        role=OrganizationRole.OWNER,
                    ),
                    OrganizationMember(
                        organization_id=preserved.id,
                        user_id=admin.id,
                        role=OrganizationRole.ADMIN,
                    ),
                    OrganizationMember(
                        organization_id=synthetic.id,
                        user_id=admin.id,
                        role=OrganizationRole.OWNER,
                    ),
                )
            )
            session.add_all(
                OrganizationPerson(
                    organization_id=synthetic.id,
                    full_name=f"Synthetic Person {index}",
                    primary_email=f"synthetic-{index}@example.test",
                )
                for index in range(100)
            )
            await session.commit()
            allowlist = _allowlist(
                admins=frozenset({admin.id}),
                protected=frozenset({superadmin.id}),
                purges=(
                    SyntheticOrganizationPurgeTarget(
                        organization_id=synthetic.id,
                        expected_person_count=100,
                    ),
                ),
                preserves=frozenset({preserved.id}),
            )
            orchestrator = _orchestrator(session)
            before = await session.scalar(
                select(User.deleted_at).where(User.id == admin.id)
            )
            plan = await orchestrator.plan(allowlist, require_storage_allowlist=True)
            assert plan.dependent_counts["synthetic_organization_people"] == 100
            assert plan.organizations == (str(synthetic.id),)
            assert plan.preserved_organizations == (str(preserved.id),)
            await session.rollback()
            assert before is None

            first = await orchestrator.execute(
                allowlist,
                confirmation="EXECUTE STAGING CLEAN SLATE",
                backup_verified=True,
                health_check=_health,
                progress=lambda _event: None,
            )
            deletion = await session.get(AccountDeletion, first[0])
            roster_item = await session.scalar(
                select(AccountDeletionItem).where(
                    AccountDeletionItem.deletion_id == first[0],
                    AccountDeletionItem.source_type == "synthetic_org_roster",
                    AccountDeletionItem.kind == "namespace",
                )
            )
            assert deletion is not None and roster_item is not None
            assert permitted_scope(deletion, roster_item)
            second = await orchestrator.execute(
                allowlist,
                confirmation="EXECUTE STAGING CLEAN SLATE",
                backup_verified=True,
                health_check=_health,
                progress=lambda _event: None,
            )
            assert second == first

        async with async_session_factory() as session:
            admin = await session.get(User, user_ids[1])
            superadmin = await session.get(User, user_ids[0])
            preserved = await session.get(Organization, organization_ids[0])
            synthetic = await session.get(Organization, organization_ids[1])
            people = await session.scalars(
                select(OrganizationPerson.id).where(
                    OrganizationPerson.organization_id == organization_ids[1]
                )
            )
            assert admin is not None and admin.deleted_at is not None and not admin.is_active
            assert superadmin is not None and superadmin.deleted_at is None
            assert preserved is not None and preserved.closed_at is None
            assert preserved.created_by_user_id == admin.id
            assert synthetic is not None and synthetic.closed_at is not None
            assert list(people) == []
            owner = await session.scalar(
                select(OrganizationMember.user_id).where(
                    OrganizationMember.organization_id == preserved.id,
                    OrganizationMember.role == OrganizationRole.OWNER,
                )
            )
            assert owner == superadmin.id
    finally:
        await _cleanup(user_ids, organization_ids)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_v2_protected_superadmin_and_preserved_owner_are_blocked() -> None:
    user_ids: list[UUID] = []
    organization_ids: list[UUID] = []
    try:
        async with async_session_factory() as session:
            superadmin = await _user(session, Role.SUPERADMIN.value)
            admin = await _user(session, Role.ADMIN.value)
            user_ids.extend((superadmin.id, admin.id))
            organization = Organization(
                id=uuid4(),
                created_by_user_id=admin.id,
                name="Preserved owner organization",
                organization_type=OrganizationType.EMPLOYER,
            )
            session.add(organization)
            await session.flush()
            organization_ids.append(organization.id)
            session.add(
                OrganizationMember(
                    organization_id=organization.id,
                    user_id=admin.id,
                    role=OrganizationRole.OWNER,
                )
            )
            await session.commit()
            orchestrator = _orchestrator(session)
            protected_target = _allowlist(
                admins=frozenset({superadmin.id}),
                protected=frozenset({superadmin.id}),
            )
            with pytest.raises(CleanSlateSafetyError, match="protected_identity_targeted"):
                await orchestrator.plan(protected_target)
            owner_target = _allowlist(
                admins=frozenset({admin.id}),
                protected=frozenset({superadmin.id}),
                preserves=frozenset({organization.id}),
            )
            with pytest.raises(
                CleanSlateSafetyError, match="preserved_organization_owned_by_target"
            ):
                await orchestrator.plan(owner_target)
    finally:
        await _cleanup(user_ids, organization_ids)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_v2_admin_requires_another_active_superadmin() -> None:
    user_ids: list[UUID] = []
    try:
        async with async_session_factory() as session:
            admin = await _user(session, Role.ADMIN.value)
            user_ids.append(admin.id)
            await session.commit()
            with pytest.raises(CleanSlateSafetyError, match="active_superadmin_required"):
                await _orchestrator(session).plan(
                    _allowlist(admins=frozenset({admin.id}))
                )
    finally:
        await _cleanup(user_ids, [])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_v2_admin_with_unresolved_assignment_is_blocked() -> None:
    user_ids: list[UUID] = []
    try:
        async with async_session_factory() as session:
            superadmin = await _user(session, Role.SUPERADMIN.value)
            admin = await _user(session, Role.ADMIN.value)
            user_ids.extend((superadmin.id, admin.id))
            session.add(
                TrustSafetyInvestigation(
                    subject_type="user",
                    subject_public_id=uuid4(),
                    title="Synthetic unresolved assignment",
                    summary="Clean Slate v2 test fixture",
                    status="open",
                    severity="low",
                    assigned_admin_user_id=admin.id,
                    created_by_user_id=superadmin.id,
                )
            )
            await session.commit()
            with pytest.raises(
                CleanSlateSafetyError, match="admin_cleanup_precondition_failed"
            ):
                await _orchestrator(session).plan(
                    _allowlist(
                        admins=frozenset({admin.id}),
                        protected=frozenset({superadmin.id}),
                    )
                )
    finally:
        await _cleanup(user_ids, [])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_v2_synthetic_activity_and_unknown_dependencies_fail_closed() -> None:
    user_ids: list[UUID] = []
    organization_ids: list[UUID] = []
    try:
        async with async_session_factory() as session:
            superadmin = await _user(session, Role.SUPERADMIN.value)
            admin = await _user(session, Role.ADMIN.value)
            user_ids.extend((superadmin.id, admin.id))
            synthetic = Organization(
                id=uuid4(),
                created_by_user_id=admin.id,
                name="Synthetic activity organization",
                organization_type=OrganizationType.UNIVERSITY,
            )
            undeclared = Organization(
                id=uuid4(),
                created_by_user_id=admin.id,
                name="Undeclared dependency",
                organization_type=OrganizationType.OTHER,
            )
            session.add_all((synthetic, undeclared))
            await session.flush()
            organization_ids.extend((synthetic.id, undeclared.id))
            session.add(
                OrganizationMember(
                    organization_id=synthetic.id,
                    user_id=admin.id,
                    role=OrganizationRole.OWNER,
                )
            )
            session.add(
                OrganizationPerson(
                    organization_id=synthetic.id,
                    full_name="Synthetic Person",
                    verification_status_summary=OrganizationPersonVerificationStatusSummary.COMPLETED,
                )
            )
            await session.commit()
            allowlist = _allowlist(
                admins=frozenset({admin.id}),
                protected=frozenset({superadmin.id}),
                purges=(
                    SyntheticOrganizationPurgeTarget(
                        organization_id=synthetic.id,
                        expected_person_count=1,
                    ),
                ),
            )
            with pytest.raises(
                CleanSlateSafetyError, match="organization_disposition_incomplete"
            ):
                await _orchestrator(session).plan(allowlist)
            declared = CleanSlateAllowlist(
                **{
                    **allowlist.__dict__,
                    "organization_preserve_ids": frozenset({undeclared.id}),
                }
            )
            with pytest.raises(
                CleanSlateSafetyError,
                match="synthetic_organization_has_verification_activity",
            ):
                await _orchestrator(session).plan(declared)
            await session.execute(
                update(OrganizationPerson)
                .where(OrganizationPerson.organization_id == synthetic.id)
                .values(
                    verification_status_summary=OrganizationPersonVerificationStatusSummary.NOT_STARTED
                )
            )
            await session.flush()

            async def unsafe_keys(_bucket, _scopes):  # noqa: ANN001, ANN202
                return {"application-static/brand/logo.png"}

            with pytest.raises(CleanSlateSafetyError, match="unknown_storage_ownership"):
                await CleanSlateOrchestrator(
                    session,
                    _settings(),
                    FakeRedis(),
                    object_lister=unsafe_keys,
                ).plan(declared)
    finally:
        await _cleanup(user_ids, organization_ids)


def _settings():
    return get_settings().model_copy(
        update={
            "s3_documents_bucket": "clean-slate-v2-test",
            "s3_document_key_prefix": "test",
            "sqs_main_queue_url": None,
        }
    )


def _orchestrator(session):  # noqa: ANN001, ANN201
    return CleanSlateOrchestrator(
        session,
        _settings(),
        FakeRedis(),
        object_lister=_empty_keys,
    )


async def _health() -> None:
    return None


async def _cleanup(user_ids: list[UUID], organization_ids: list[UUID]) -> None:
    async with async_session_factory() as session:
        deletion_ids = select(AccountDeletion.id).where(AccountDeletion.user_id.in_(user_ids))
        await session.execute(
            delete(AccountDeletionItem).where(AccountDeletionItem.deletion_id.in_(deletion_ids))
        )
        await session.execute(
            delete(OrganizationDeletionResolution).where(
                OrganizationDeletionResolution.organization_id.in_(organization_ids)
            )
        )
        await session.execute(
            update(User).where(User.id.in_(user_ids)).values(active_organization_id=None)
        )
        await session.execute(
            delete(TrustSafetyInvestigation).where(
                TrustSafetyInvestigation.assigned_admin_user_id.in_(user_ids)
            )
        )
        await session.execute(delete(Organization).where(Organization.id.in_(organization_ids)))
        await session.execute(delete(AccountDeletion).where(AccountDeletion.user_id.in_(user_ids)))
        await session.execute(delete(User).where(User.id.in_(user_ids)))
        await session.commit()
