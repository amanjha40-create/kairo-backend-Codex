"""Deterministic successor policy, without database or provider access."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import permutations
from uuid import UUID

import pytest

from app.organization.account_deletion_policy import (
    MembershipSnapshot,
    OwnershipAction,
    decide_ownership_on_deletion,
)
from app.organization.enums import OrganizationRole

NOW = datetime(2026, 10, 22, tzinfo=UTC)


def member(number, role=OrganizationRole.MEMBER, **overrides):
    return replace(
        MembershipSnapshot(
            user_id=UUID(int=number),
            membership_id=UUID(int=number + 100),
            role=role,
            joined_at=NOW,
            user_active=True,
            user_deleted=False,
            membership_suspended=False,
        ),
        **overrides,
    )


OWNER = member(1, OrganizationRole.OWNER)


def decide(*others, **kwargs):
    return decide_ownership_on_deletion(OWNER.user_id, (OWNER, *others), **kwargs)


def test_no_membership_requires_no_ownership_action():
    assert decide_ownership_on_deletion(OWNER.user_id, ()).action == OwnershipAction.LEAVE


def test_non_owner_can_leave_without_changing_ownership():
    actor = member(2)
    result = decide_ownership_on_deletion(actor.user_id, (OWNER, actor))
    assert result.action == OwnershipAction.LEAVE


def test_active_admin_precedes_older_member():
    result = decide(
        member(2, joined_at=NOW - timedelta(days=30)), member(3, OrganizationRole.ADMIN)
    )
    assert result.action == OwnershipAction.TRANSFER
    assert result.successor_user_id == UUID(int=3)
    assert result.successor_membership_id == UUID(int=103)


def test_oldest_eligible_member_selected_without_admin():
    result = decide(member(2), member(3, joined_at=NOW - timedelta(days=1)))
    assert result.successor_user_id == UUID(int=3)


def test_oldest_admin_selected():
    result = decide(
        member(2, OrganizationRole.ADMIN),
        member(3, OrganizationRole.ADMIN, joined_at=NOW - timedelta(days=1)),
    )
    assert result.successor_user_id == UUID(int=3)


def test_sole_owner_closes_organization():
    result = decide()
    assert result.action == OwnershipAction.CLOSE
    assert result.successor_user_id is None


@pytest.mark.parametrize(
    "invalid",
    [
        {"pending": True},
        {"user_active": False},
        {"user_deleted": True},
        {"membership_suspended": True},
    ],
)
def test_invalid_admin_cannot_receive_ownership(invalid):
    result = decide(member(2, OrganizationRole.ADMIN, **invalid), member(3))
    assert result.successor_user_id == UUID(int=3)


@pytest.mark.parametrize(
    "invalid",
    [
        {"pending": True},
        {"user_active": False},
        {"user_deleted": True},
        {"membership_suspended": True},
    ],
)
def test_only_invalid_successor_requires_closure(invalid):
    assert decide(member(2, **invalid)).action == OwnershipAction.CLOSE


def test_existing_active_coowner_is_preserved():
    assert decide(member(2, OrganizationRole.OWNER), member(3)).action == OwnershipAction.LEAVE


def test_inactive_coowner_does_not_satisfy_owner_invariant():
    result = decide(member(2, OrganizationRole.OWNER, user_active=False), member(3))
    assert result.action == OwnershipAction.TRANSFER
    assert result.successor_user_id == UUID(int=3)


def test_closed_organization_is_not_reopened():
    assert decide(member(2), organization_closed=True).action == OwnershipAction.LEAVE


def test_reviewer_is_eligible_active_member():
    assert decide(member(2, OrganizationRole.REVIEWER)).successor_user_id == UUID(int=2)


def test_order_and_repeated_evaluation_do_not_change_decision():
    rows = (OWNER, member(3), member(2))
    expected = decide_ownership_on_deletion(OWNER.user_id, rows)
    assert expected.successor_user_id == UUID(int=2)
    for ordered in permutations(rows):
        assert decide_ownership_on_deletion(OWNER.user_id, ordered) == expected


def test_timezone_equivalent_join_times_use_uuid_tie_break():
    from datetime import timezone

    other_zone = NOW.astimezone(timezone(timedelta(hours=5, minutes=30)))
    assert decide(member(3), member(2, joined_at=other_zone)).successor_user_id == UUID(int=2)


def test_naive_timestamp_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        member(2, joined_at=NOW.replace(tzinfo=None))


def test_duplicate_user_snapshot_is_rejected():
    with pytest.raises(ValueError, match="duplicate users"):
        decide(member(2), member(2, membership_id=UUID(int=999)))


def test_duplicate_membership_snapshot_is_rejected():
    with pytest.raises(ValueError, match="duplicate memberships"):
        decide(member(2), member(3, membership_id=UUID(int=102)))
