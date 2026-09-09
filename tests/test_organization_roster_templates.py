"""Focused route and contract tests for canonical roster CSV templates."""

from __future__ import annotations

import csv
import inspect
import io
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient, Response

from app.api.dependencies.auth import CurrentUser, get_current_user
from app.api.dependencies.services import get_organization_roster_import_service
from app.exceptions import ForbiddenError, NotFoundError
from app.main import app
from app.organization_roster_import.enums import OrganizationRosterType
from app.organization_roster_import.headers import (
    alias_dictionary,
    allowed_fields,
    normalize_header,
    template_columns,
)
from app.organization_roster_import.templates import (
    EMPLOYEE_TEMPLATE_FILENAME,
    STUDENT_TEMPLATE_FILENAME,
    build_roster_template,
)
from app.services.organization_roster_import_service import OrganizationRosterImportService

ORG_ID = UUID("00000000-0000-0000-0000-000000000101")
OTHER_ORG_ID = UUID("00000000-0000-0000-0000-000000000102")
OWNER_ID = UUID("00000000-0000-0000-0000-000000000201")
ADMIN_ID = UUID("00000000-0000-0000-0000-000000000202")
MEMBER_ID = UUID("00000000-0000-0000-0000-000000000203")
OUTSIDER_ID = UUID("00000000-0000-0000-0000-000000000204")

EMPLOYEE_HEADERS = [
    "Employee ID",
    "Full Name",
    "Work Email",
    "Phone",
    "Department",
    "Designation",
    "Employment Type",
    "Joining Date",
    "Exit Date",
    "Employment Status",
    "Location",
]
STUDENT_HEADERS = [
    "Student ID",
    "Full Name",
    "Institution Email",
    "Phone",
    "Degree",
    "Program",
    "Specialization",
    "Department",
    "Admission Date",
    "Graduation Date",
    "Enrollment Status",
    "Campus",
    "Cohort",
]


class TemplateAuthorizationService:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID]] = []

    async def authorize_template_download(
        self, *, actor_user_id: UUID, org_public_id: UUID
    ) -> None:
        self.calls.append((actor_user_id, org_public_id))
        if actor_user_id == MEMBER_ID:
            raise ForbiddenError("Only organization owners or admins can manage rosters")
        if actor_user_id == OUTSIDER_ID or org_public_id == OTHER_ORG_ID:
            raise NotFoundError("Organization not found")


def _current_user(user_id: UUID) -> CurrentUser:
    return CurrentUser(id=user_id, email="roster-manager@kairo.test", role="user")


async def _download(path: str, user_id: UUID) -> tuple[Response, TemplateAuthorizationService]:
    service = TemplateAuthorizationService()

    async def override_current_user() -> CurrentUser:
        return _current_user(user_id)

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_organization_roster_import_service] = lambda: service
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get(path)
    finally:
        app.dependency_overrides.clear()
    return response, service


@pytest.mark.asyncio
@pytest.mark.parametrize("user_id", [OWNER_ID, ADMIN_ID])
@pytest.mark.parametrize(
    ("endpoint", "filename", "headers"),
    [
        ("employee.csv", EMPLOYEE_TEMPLATE_FILENAME, EMPLOYEE_HEADERS),
        ("student.csv", STUDENT_TEMPLATE_FILENAME, STUDENT_HEADERS),
    ],
)
async def test_owner_and_admin_download_exact_header_only_csv(
    user_id: UUID,
    endpoint: str,
    filename: str,
    headers: list[str],
) -> None:
    path = f"/api/v1/organizations/{ORG_ID}/roster/templates/{endpoint}"
    response, service = await _download(path, user_id)

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == f'attachment; filename="{filename}"'
    assert list(csv.reader(io.StringIO(response.text))) == [headers]
    assert service.calls == [(user_id, ORG_ID)]


@pytest.mark.asyncio
async def test_normal_member_is_denied() -> None:
    path = f"/api/v1/organizations/{ORG_ID}/roster/templates/employee.csv"
    response, _ = await _download(path, MEMBER_ID)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_cross_organization_access_fails_closed() -> None:
    path = f"/api/v1/organizations/{OTHER_ORG_ID}/roster/templates/student.csv"
    response, _ = await _download(path, OUTSIDER_ID)
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("roster_type", "expected_filename", "expected_headers"),
    [
        (OrganizationRosterType.EMPLOYEE, EMPLOYEE_TEMPLATE_FILENAME, EMPLOYEE_HEADERS),
        (OrganizationRosterType.STUDENT, STUDENT_TEMPLATE_FILENAME, STUDENT_HEADERS),
    ],
)
def test_template_contract_aligns_with_supported_import_fields(
    roster_type: OrganizationRosterType,
    expected_filename: str,
    expected_headers: list[str],
) -> None:
    columns = template_columns(roster_type)
    filename, content = build_roster_template(roster_type)
    parsed_rows = list(csv.reader(io.StringIO(content)))

    assert filename == expected_filename
    assert [display_name for display_name, _ in columns] == expected_headers
    assert {field for _, field in columns} <= allowed_fields(roster_type)
    aliases = alias_dictionary(roster_type)
    assert all(aliases[normalize_header(header)] == field for header, field in columns)
    assert parsed_rows == [expected_headers]


def test_template_path_has_no_mutating_or_external_side_effects() -> None:
    source = "\n".join(
        (
            inspect.getsource(build_roster_template),
            inspect.getsource(OrganizationRosterImportService.authorize_template_download),
        )
    )
    prohibited = (
        "commit(",
        "flush(",
        "put_private(",
        "S3",
        "send_email(",
        "send_sms(",
        "create_outreach(",
        "Candidate(",
    )
    assert all(token not in source for token in prohibited)
