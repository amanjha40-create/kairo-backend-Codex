"""Focused Administrator-directory filter contract tests."""

from __future__ import annotations

from typing import Any

import pytest

from app.config import get_settings
from app.schemas.admin_settings import AdminAdministratorListParams
from app.services.admin_settings_service import AdminSettingsService


class _EmptyScalars:
    def all(self) -> list[object]:
        return []


class _EmptyResult:
    def scalars(self) -> _EmptyScalars:
        return _EmptyScalars()


class _CaptureSession:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def scalar(self, statement: Any) -> int:
        self.statements.append(statement)
        return 0

    async def execute(self, statement: Any) -> _EmptyResult:
        self.statements.append(statement)
        return _EmptyResult()


def _compiled(statement: Any) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True})).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("params", "expected_fragments"),
    [
        (
            AdminAdministratorListParams(role="support"),
            ("users.role = 'support'",),
        ),
        (
            AdminAdministratorListParams(status="suspended"),
            ("users.is_active is false", "users.suspended_at is not null"),
        ),
        (
            AdminAdministratorListParams(role="support", status="suspended"),
            (
                "users.role = 'support'",
                "users.is_active is false",
                "users.suspended_at is not null",
            ),
        ),
        (
            AdminAdministratorListParams(role="admin", search="ada"),
            ("users.role = 'admin'", "lower(users.full_name) like lower('%ada%')"),
        ),
    ],
)
async def test_administrator_filters_reach_the_database_query(
    params: AdminAdministratorListParams,
    expected_fragments: tuple[str, ...],
) -> None:
    session = _CaptureSession()
    service = AdminSettingsService(session, get_settings())  # type: ignore[arg-type]

    await service.list_administrators(params)

    assert len(session.statements) == 2
    compiled = _compiled(session.statements[1])
    assert "users.deleted_at is null" in compiled
    assert "users.role in" in compiled
    for fragment in expected_fragments:
        assert fragment in compiled


@pytest.mark.asyncio
async def test_administrator_filter_preserves_pagination_and_candidate_exclusion() -> None:
    session = _CaptureSession()
    service = AdminSettingsService(session, get_settings())  # type: ignore[arg-type]

    page = await service.list_administrators(
        AdminAdministratorListParams(page=2, page_size=5, role="moderator", status="active")
    )

    compiled = _compiled(session.statements[1])
    assert "users.deleted_at is null" in compiled
    assert "users.role in" in compiled
    assert "users.role = 'moderator'" in compiled
    assert "users.is_active is true" in compiled
    assert "limit 5" in compiled
    assert "offset 5" in compiled
    assert page.page == 2
    assert page.page_size == 5


@pytest.mark.parametrize("role", ["user", "candidate", "owner", "arbitrary"])
def test_administrator_filter_rejects_non_sanctioned_roles(role: str) -> None:
    with pytest.raises(ValueError, match="sanctioned Admin role"):
        AdminAdministratorListParams(role=role)
