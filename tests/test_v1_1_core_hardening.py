"""Synthetic regressions for the source-only V1.1 audit."""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.config import Settings
from app.core.constants import MAX_PAGE_SIZE
from app.schemas.pagination import ListQueryParams, filter_sort_paginate
from app.schemas.user import UserUpdate
from app.services.user_service import UserService


@pytest.mark.parametrize("phone", [None, "", "   "])
async def test_clearing_phone_invalidates_its_verification(phone):
    user = SimpleNamespace(
        id=uuid4(),
        phone="+919876543210",
        phone_verified_at=datetime.now(UTC),
        email_verified_at=None,
        employment_onboarding_completed_at=None,
        full_name=None,
        headline=None,
        current_role=None,
        industry=None,
        years_of_experience=None,
    )
    session = AsyncMock()
    service = UserService(session, Settings())
    service._users = SimpleNamespace(get_by_id=AsyncMock(return_value=user))
    service._to_public = AsyncMock(return_value=user)
    await service.update_profile(user.id, UserUpdate(phone=phone))
    assert user.phone is None
    assert user.phone_verified_at is None
    session.commit.assert_awaited_once()


@pytest.mark.parametrize("bound", [date(2026, 1, 2), datetime(2026, 1, 2)])
def test_date_filters_compare_safely_with_utc_records(bound):
    rows = [SimpleNamespace(created_at=datetime(2026, 1, 2, 12, tzinfo=UTC))]
    result = filter_sort_paginate(rows, params=ListQueryParams(created_after=bound))
    assert result == rows


def test_date_before_includes_the_full_utc_day():
    rows = [
        SimpleNamespace(created_at=datetime(2026, 1, 2, 23, 59, 59, tzinfo=UTC)),
        SimpleNamespace(created_at=datetime(2026, 1, 3, tzinfo=UTC)),
    ]
    assert (
        filter_sort_paginate(rows, params=ListQueryParams(created_before=date(2026, 1, 2)))
        == rows[:1]
    )


@pytest.mark.parametrize("count", [0, 1, MAX_PAGE_SIZE + 1])
def test_legacy_unpaginated_envelope_does_not_apply_query_limit_to_total(count):
    rows = list(range(count))
    result = filter_sort_paginate(rows, params=ListQueryParams(), force_page_envelope=True)
    assert result.items == rows and result.total == count
    assert result.page_size == max(count, 1)
    assert result.total_pages == (1 if count else 0)


def test_requested_pagination_still_bounds_results():
    rows = list(range(MAX_PAGE_SIZE + 1))
    result = filter_sort_paginate(
        rows, params=ListQueryParams(page_size=2), force_page_envelope=True
    )
    assert result.items == [0, 1] and result.total == len(rows)
    assert result.page_size == 2
