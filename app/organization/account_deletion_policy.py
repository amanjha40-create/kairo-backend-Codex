"""Pure ownership decisions for the coordinated account-deletion transaction.

This module does not grant authority to mutate an organization. The orchestrator
must supply a complete, locked membership snapshot and apply the decision in the
same transaction as account erasure and the durable cleanup inventory.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.organization.enums import OrganizationRole


class OwnershipAction(StrEnum):
    LEAVE = "leave"
    TRANSFER = "transfer"
    CLOSE = "close"


@dataclass(frozen=True, slots=True)
class MembershipSnapshot:
    user_id: UUID
    membership_id: UUID
    role: OrganizationRole
    joined_at: datetime
    user_active: bool
    user_deleted: bool
    membership_suspended: bool
    pending: bool = False

    def __post_init__(self) -> None:
        if self.joined_at.tzinfo is None or self.joined_at.utcoffset() is None:
            raise ValueError("Membership ordering requires a timezone-aware timestamp")

    @property
    def eligible(self) -> bool:
        return (
            self.user_active
            and not self.user_deleted
            and not self.membership_suspended
            and not self.pending
        )


@dataclass(frozen=True, slots=True)
class OwnershipDecision:
    action: OwnershipAction
    successor_user_id: UUID | None = None
    successor_membership_id: UUID | None = None


def decide_ownership_on_deletion(
    deleting_user_id: UUID,
    members: tuple[MembershipSnapshot, ...],
    *,
    organization_closed: bool = False,
    repair_missing_owner: bool = False,
) -> OwnershipDecision:
    """Choose a successor deterministically without modifying the snapshot.

    An eligible co-owner already satisfies the ownership invariant. Otherwise,
    admins take priority over ordinary members/reviewers. Age ties are broken by
    user UUID and then membership UUID, independent of database result ordering.
    """
    if len({member.user_id for member in members}) != len(members):
        raise ValueError("Membership snapshot contains duplicate users")
    if len({member.membership_id for member in members}) != len(members):
        raise ValueError("Membership snapshot contains duplicate memberships")
    if organization_closed:
        return OwnershipDecision(OwnershipAction.LEAVE)
    actor = next((member for member in members if member.user_id == deleting_user_id), None)
    if actor is None or (actor.role != OrganizationRole.OWNER and not repair_missing_owner):
        return OwnershipDecision(OwnershipAction.LEAVE)

    eligible = [
        member for member in members if member.user_id != deleting_user_id and member.eligible
    ]
    if any(member.role == OrganizationRole.OWNER for member in eligible):
        return OwnershipDecision(OwnershipAction.LEAVE)
    if not eligible:
        return OwnershipDecision(OwnershipAction.CLOSE)
    successor = min(
        eligible,
        key=lambda member: (
            member.role != OrganizationRole.ADMIN,
            member.joined_at,
            member.user_id.int,
            member.membership_id.int,
        ),
    )
    return OwnershipDecision(
        OwnershipAction.TRANSFER,
        successor.user_id,
        successor.membership_id,
    )
