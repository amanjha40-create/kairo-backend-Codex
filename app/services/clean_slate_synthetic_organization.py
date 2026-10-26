"""Exact-manifest synthetic organization purge for the clean-slate operator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, select

from app.models import (
    InstitutionVerificationRequest,
    Organization,
    OrganizationActivityEvent,
    OrganizationInvitation,
    OrganizationJobRole,
    OrganizationMember,
    OrganizationPerson,
    OrganizationRosterImport,
    TrustInvitation,
    VerificationRequest,
)
from app.models.account_deletion import AccountDeletion, AccountDeletionItem
from app.models.court_record_check import CourtRecordCheck
from app.models.in_person_verification import InPersonVerificationRecord
from app.models.organization_deletion_resolution import OrganizationDeletionResolution
from app.organization.enums import OrganizationInvitationStatus, OrganizationRole
from app.organization_people.enums import OrganizationPersonVerificationStatusSummary
from app.services.account_deletion_inventory import identity, safe_key
from app.services.organization_account_deletion import close_organization_for_account_deletion
from app.trust_invitations.enums import TrustInvitationStatus


class SyntheticOrganizationPurgeError(RuntimeError):
    """Stable fail-closed reason without organization or person content."""


@dataclass(frozen=True)
class SyntheticOrganizationPurgeTarget:
    organization_id: UUID
    expected_person_count: int


@dataclass(frozen=True)
class SyntheticOrganizationPurgeState:
    person_count: int
    member_count: int
    verification_activity_count: int
    accepted_invitation_count: int
    linked_person_count: int
    already_purged: bool


async def inspect_synthetic_organization_purge(
    session,
    target: SyntheticOrganizationPurgeTarget,
    *,
    approved_user_ids: frozenset[UUID],
    lock: bool = False,
) -> SyntheticOrganizationPurgeState:
    query = select(Organization).where(Organization.id == target.organization_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    organization = await session.scalar(query)
    if organization is None:
        raise SyntheticOrganizationPurgeError("synthetic_organization_not_found")
    if target.expected_person_count < 0:
        raise SyntheticOrganizationPurgeError("invalid_expected_person_count")

    person_count = int(
        await session.scalar(
            select(func.count()).select_from(OrganizationPerson).where(
                OrganizationPerson.organization_id == organization.id
            )
        )
        or 0
    )
    member_count = int(
        await session.scalar(
            select(func.count()).select_from(OrganizationMember).where(
                OrganizationMember.organization_id == organization.id
            )
        )
        or 0
    )
    linked_person_count = int(
        await session.scalar(
            select(func.count()).select_from(OrganizationPerson).where(
                OrganizationPerson.organization_id == organization.id,
                OrganizationPerson.linked_user_id.is_not(None),
            )
        )
        or 0
    )
    request_count = int(
        await session.scalar(
            select(func.count()).select_from(VerificationRequest).where(
                VerificationRequest.organization_id == organization.id
            )
        )
        or 0
    )
    institution_request_count = int(
        await session.scalar(
            select(func.count()).select_from(InstitutionVerificationRequest).where(
                InstitutionVerificationRequest.organization_id == organization.id
            )
        )
        or 0
    )
    in_person_count = int(
        await session.scalar(
            select(func.count()).select_from(InPersonVerificationRecord).where(
                InPersonVerificationRecord.organization_id == organization.id
            )
        )
        or 0
    )
    court_count = int(
        await session.scalar(
            select(func.count()).select_from(CourtRecordCheck).where(
                CourtRecordCheck.organization_id == organization.id
            )
        )
        or 0
    )
    person_activity_count = int(
        await session.scalar(
            select(func.count()).select_from(OrganizationPerson).where(
                OrganizationPerson.organization_id == organization.id,
                OrganizationPerson.verification_status_summary
                != OrganizationPersonVerificationStatusSummary.NOT_STARTED,
            )
        )
        or 0
    )
    verification_activity_count = (
        request_count
        + institution_request_count
        + in_person_count
        + court_count
        + person_activity_count
    )
    accepted_org_invites = int(
        await session.scalar(
            select(func.count()).select_from(OrganizationInvitation).where(
                OrganizationInvitation.organization_id == organization.id,
                OrganizationInvitation.status == OrganizationInvitationStatus.ACCEPTED,
            )
        )
        or 0
    )
    accepted_trust_invites = int(
        await session.scalar(
            select(func.count()).select_from(TrustInvitation).where(
                TrustInvitation.organization_id == organization.id,
                TrustInvitation.status == TrustInvitationStatus.ACCEPTED,
            )
        )
        or 0
    )
    accepted_invitation_count = accepted_org_invites + accepted_trust_invites

    already_purged = organization.closed_at is not None and person_count == member_count == 0
    if already_purged:
        return SyntheticOrganizationPurgeState(
            person_count=0,
            member_count=0,
            verification_activity_count=verification_activity_count,
            accepted_invitation_count=accepted_invitation_count,
            linked_person_count=linked_person_count,
            already_purged=True,
        )
    if organization.closed_at is not None:
        raise SyntheticOrganizationPurgeError("closed_organization_has_live_domain_state")
    if person_count != target.expected_person_count:
        raise SyntheticOrganizationPurgeError("synthetic_person_count_mismatch")
    if verification_activity_count:
        raise SyntheticOrganizationPurgeError("synthetic_organization_has_verification_activity")
    if accepted_invitation_count:
        raise SyntheticOrganizationPurgeError("synthetic_organization_has_accepted_invitation")
    if linked_person_count:
        raise SyntheticOrganizationPurgeError("synthetic_organization_has_linked_person")

    memberships = list(
        (
            await session.scalars(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == organization.id
                )
            )
        ).all()
    )
    if not memberships or any(row.user_id not in approved_user_ids for row in memberships):
        raise SyntheticOrganizationPurgeError("synthetic_organization_has_external_member")
    owners = [row for row in memberships if row.role == OrganizationRole.OWNER]
    if len(owners) != 1:
        raise SyntheticOrganizationPurgeError("synthetic_organization_owner_mismatch")

    return SyntheticOrganizationPurgeState(
        person_count=person_count,
        member_count=member_count,
        verification_activity_count=0,
        accepted_invitation_count=0,
        linked_person_count=0,
        already_purged=False,
    )


async def purge_synthetic_organization_for_clean_slate(
    session,
    settings,
    deletion: AccountDeletion,
    target: SyntheticOrganizationPurgeTarget,
    *,
    approved_user_ids: frozenset[UUID],
) -> None:
    state = await inspect_synthetic_organization_purge(
        session,
        target,
        approved_user_ids=approved_user_ids,
        lock=True,
    )
    if state.already_purged:
        return

    organization = await session.get(Organization, target.organization_id)
    if organization is None:
        raise SyntheticOrganizationPurgeError("synthetic_organization_not_found")
    imports = list(
        (
            await session.scalars(
                select(OrganizationRosterImport).where(
                    OrganizationRosterImport.organization_id == organization.id
                )
            )
        ).all()
    )
    prefix = settings.s3_document_key_prefix.strip("/")
    roster_scope = f"{prefix}/organization-rosters/organizations/{organization.id}/"
    for row in imports:
        key = row.source_storage_key
        valid = safe_key(key) and key.startswith(roster_scope)
        session.add(
            AccountDeletionItem(
                deletion_id=deletion.id,
                identity_hash=identity("object", key),
                source_type="synthetic_org_roster",
                source_id=organization.id,
                kind="object",
                object_key=key if valid else None,
                scope_prefix=roster_scope,
                status="pending" if valid else "review",
                last_error_category=None if valid else "unsafe_legacy_reference",
                next_attempt_at=deletion.next_attempt_at,
            )
        )
    session.add(
        AccountDeletionItem(
            deletion_id=deletion.id,
            identity_hash=identity("namespace", roster_scope),
            source_type="synthetic_org_roster",
            source_id=organization.id,
            kind="namespace",
            object_key=roster_scope,
            scope_prefix=roster_scope,
            status="pending",
            next_attempt_at=deletion.next_attempt_at,
        )
    )

    now = datetime.now(UTC)
    await close_organization_for_account_deletion(session, organization, deletion, now)
    await session.execute(
        delete(OrganizationRosterImport).where(
            OrganizationRosterImport.organization_id == organization.id
        )
    )
    await session.execute(
        delete(OrganizationInvitation).where(
            OrganizationInvitation.organization_id == organization.id
        )
    )
    await session.execute(
        delete(TrustInvitation).where(TrustInvitation.organization_id == organization.id)
    )
    await session.execute(
        delete(OrganizationActivityEvent).where(
            OrganizationActivityEvent.organization_id == organization.id
        )
    )
    await session.execute(
        delete(OrganizationPerson).where(OrganizationPerson.organization_id == organization.id)
    )
    await session.execute(
        delete(OrganizationJobRole).where(
            OrganizationJobRole.organization_id == organization.id
        )
    )
    session.add(
        OrganizationDeletionResolution(
            deletion_id=deletion.id,
            organization_id=organization.id,
            action="close",
            successor_user_id=None,
        )
    )
    await session.flush()

    remaining_people = int(
        await session.scalar(
            select(func.count()).select_from(OrganizationPerson).where(
                OrganizationPerson.organization_id == organization.id
            )
        )
        or 0
    )
    remaining_members = int(
        await session.scalar(
            select(func.count()).select_from(OrganizationMember).where(
                OrganizationMember.organization_id == organization.id
            )
        )
        or 0
    )
    if remaining_people or remaining_members or organization.closed_at is None:
        raise SyntheticOrganizationPurgeError("synthetic_organization_purge_incomplete")
