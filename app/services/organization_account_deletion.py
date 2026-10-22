"""Transactional organization resolution; no commits or external side effects."""

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, select, update

from app.models import (
    EmployerVerificationRequest,
    InstitutionPersonConsent,
    InstitutionVerificationRequest,
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    OrganizationPerson,
    OrganizationPersonPassportAccess,
    TrustInvitation,
    User,
    VerificationRequest,
)
from app.models.account_deletion import AccountDeletionItem
from app.models.organization_deletion_resolution import OrganizationDeletionResolution
from app.models.organization_logo_upload import OrganizationLogoUpload
from app.organization.account_deletion_policy import (
    MembershipSnapshot,
    OwnershipAction,
    decide_ownership_on_deletion,
)
from app.organization.enums import OrganizationInvitationStatus, OrganizationRole
from app.organization_people.enums import OrganizationPersonPassportAccessState
from app.services.account_deletion_inventory import identity, safe_key
from app.trust_invitations.enums import TrustInvitationStatus


async def close_organization_for_account_deletion(session, organization, deletion, now):
    """Canonical permanent closure, retaining shared records behind revoked access.

    Caller owns the org/member/user locks and has proven no eligible successor.
    Roster sources keep their existing retention contract; only the non-retained
    organization logo namespace enters personal-deletion-driven physical cleanup.
    """
    if organization.closed_at is not None:
        return
    eligible_other = await session.scalar(
        select(OrganizationMember.id)
        .join(User, User.id == OrganizationMember.user_id)
        .where(
            OrganizationMember.organization_id == organization.id,
            OrganizationMember.user_id != deletion.user_id,
            OrganizationMember.suspended_at.is_(None),
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
        .limit(1)
    )
    if eligible_other is not None:
        raise RuntimeError("organization_closure_has_eligible_member")
    await session.execute(
        update(InstitutionPersonConsent)
        .where(InstitutionPersonConsent.organization_id == organization.id)
        .values(revoked_at=now, allowed_fields=[])
    )
    request_ids = select(VerificationRequest.id).where(
        VerificationRequest.organization_id == organization.id
    )
    await session.execute(
        update(EmployerVerificationRequest)
        .where(EmployerVerificationRequest.verification_request_id.in_(request_ids))
        .values(revoked_at=now)
    )
    await session.execute(
        update(InstitutionVerificationRequest)
        .where(InstitutionVerificationRequest.organization_id == organization.id)
        .values(revoked_at=now)
    )
    people_ids = select(OrganizationPerson.id).where(
        OrganizationPerson.organization_id == organization.id
    )
    await session.execute(
        update(OrganizationPersonPassportAccess)
        .where(OrganizationPersonPassportAccess.organization_person_id.in_(people_ids))
        .values(
            access_state=OrganizationPersonPassportAccessState.REVOKED,
            revoked_at=now,
            permissions_snapshot={},
        )
    )
    await session.execute(
        update(OrganizationInvitation)
        .where(OrganizationInvitation.organization_id == organization.id)
        .values(token_hash=None, token_revoked_at=now, token_expires_at=now)
    )
    await session.execute(
        update(OrganizationInvitation)
        .where(
            OrganizationInvitation.organization_id == organization.id,
            OrganizationInvitation.status == OrganizationInvitationStatus.PENDING,
        )
        .values(status=OrganizationInvitationStatus.CANCELLED, cancelled_at=now)
    )
    for invitation in (
        await session.scalars(
            select(TrustInvitation)
            .where(TrustInvitation.organization_id == organization.id)
            .with_for_update()
        )
    ).all():
        invitation.token_hash = hashlib.sha256(uuid4().bytes).hexdigest()
        invitation.expires_at = now
        if invitation.status in {TrustInvitationStatus.DRAFT, TrustInvitationStatus.PENDING}:
            invitation.status = TrustInvitationStatus.CANCELLED
            invitation.cancelled_at = now

    # Flush capability revocation while the locked organization is still open;
    # ORM table ordering must not persist closure ahead of these revocations.
    await session.flush()

    # Membership access disappears, but organization-owned verification/registry
    # history and creator tombstones are never cascade-deleted.
    await session.execute(
        delete(OrganizationMember).where(OrganizationMember.organization_id == organization.id)
    )
    await session.execute(
        update(User)
        .where(User.active_organization_id == organization.id)
        .values(active_organization_id=None)
    )
    await session.execute(
        update(OrganizationLogoUpload)
        .where(OrganizationLogoUpload.organization_id == organization.id)
        .values(expires_at=now)
    )
    scope = f"{deletion.storage_prefix}/organizations/{organization.id}/logo/"
    logo_keys = set(
        (
            await session.scalars(
                select(OrganizationLogoUpload.object_key).where(
                    OrganizationLogoUpload.organization_id == organization.id
                )
            )
        ).all()
    )
    if organization.logo_object_key:
        logo_keys.add(organization.logo_object_key)
    for key in logo_keys:
        valid = safe_key(key) and key.startswith(scope)
        session.add(
            AccountDeletionItem(
                deletion_id=deletion.id,
                identity_hash=identity("object", key),
                source_type="closed_org_logo",
                source_id=organization.id,
                kind="object",
                object_key=key if valid else None,
                scope_prefix=scope,
                status="pending" if valid else "review",
                last_error_category=None if valid else "unsafe_legacy_reference",
                next_attempt_at=deletion.next_attempt_at,
            )
        )
    session.add(
        AccountDeletionItem(
            deletion_id=deletion.id,
            identity_hash=identity("namespace", scope),
            source_type="closed_org_logo",
            source_id=organization.id,
            kind="namespace",
            object_key=scope,
            scope_prefix=scope,
            status="pending",
            next_attempt_at=deletion.next_attempt_at,
        )
    )
    organization.logo_object_key = None
    organization.logo_content_type = None
    organization.logo_byte_size = None
    organization.closed_at = now
    organization.closure_deletion_id = deletion.id
    organization.suspended_at = organization.suspended_at or now
    organization.suspension_reason = "Permanently closed through account deletion"
    await session.flush()


async def resolve_organizations_for_account_deletion(session, user, deletion):
    """Resolve memberships atomically inside the existing deletion transaction.

    Org locks serialize joins/role changes. User locks revalidate successor state.
    NOWAIT avoids the inverse order of another request already locking its actor;
    contention aborts the complete deletion transaction, without partial transfer.
    """
    org_ids = select(OrganizationMember.organization_id).where(
        OrganizationMember.user_id == user.id
    )
    organizations = (
        await session.scalars(
            select(Organization)
            .where(Organization.id.in_(org_ids))
            .order_by(Organization.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()
    now = datetime.now(UTC)
    for organization in organizations:
        members = (
            await session.scalars(
                select(OrganizationMember)
                .where(OrganizationMember.organization_id == organization.id)
                .order_by(OrganizationMember.user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
        users = {
            row.id: row
            for row in (
                await session.scalars(
                    select(User)
                    .where(User.id.in_([member.user_id for member in members]))
                    .order_by(User.id)
                    .with_for_update(nowait=True)
                    .execution_options(populate_existing=True)
                )
            ).all()
        }
        snapshots = tuple(
            MembershipSnapshot(
                user_id=row.user_id,
                membership_id=row.id,
                role=row.role,
                joined_at=row.created_at,
                user_active=users[row.user_id].is_active,
                user_deleted=users[row.user_id].deleted_at is not None,
                membership_suspended=row.suspended_at is not None,
            )
            for row in members
        )
        decision = decide_ownership_on_deletion(
            user.id,
            snapshots,
            organization_closed=organization.closed_at is not None,
            repair_missing_owner=not any(
                row.role == OrganizationRole.OWNER and row.eligible for row in snapshots
            ),
        )
        if decision.action == OwnershipAction.TRANSFER:
            successor = next(row for row in members if row.id == decision.successor_membership_id)
            successor.role = OrganizationRole.OWNER
            await session.flush()
        elif decision.action == OwnershipAction.CLOSE:
            await close_organization_for_account_deletion(session, organization, deletion, now)
        await session.execute(
            delete(OrganizationMember).where(
                OrganizationMember.organization_id == organization.id,
                OrganizationMember.user_id == user.id,
            )
        )
        session.add(
            OrganizationDeletionResolution(
                deletion_id=deletion.id,
                organization_id=organization.id,
                action=decision.action.value,
                successor_user_id=decision.successor_user_id,
            )
        )
        if organization.closed_at is None:
            owner = await session.scalar(
                select(OrganizationMember.id)
                .join(User, User.id == OrganizationMember.user_id)
                .where(
                    OrganizationMember.organization_id == organization.id,
                    OrganizationMember.role == OrganizationRole.OWNER,
                    OrganizationMember.suspended_at.is_(None),
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                )
                .limit(1)
            )
            if owner is None:
                raise RuntimeError("organization_owner_invariant_failed")

    # A pending invitation is never a membership/successor. Invalidate this
    # account's invitation capabilities without touching other invitees.
    await session.execute(
        update(OrganizationInvitation)
        .where(
            (OrganizationInvitation.invitee_user_id == user.id)
            | (OrganizationInvitation.invitee_email == user.email)
        )
        .values(token_hash=None, token_revoked_at=now, token_expires_at=now)
    )
    await session.execute(
        update(OrganizationInvitation)
        .where(
            (
                (OrganizationInvitation.invitee_user_id == user.id)
                | (OrganizationInvitation.invitee_email == user.email)
            ),
            OrganizationInvitation.status == OrganizationInvitationStatus.PENDING,
        )
        .values(status=OrganizationInvitationStatus.CANCELLED, cancelled_at=now)
    )
