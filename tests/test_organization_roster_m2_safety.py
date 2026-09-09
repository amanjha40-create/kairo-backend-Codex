"""Boundary and route-contract safety checks for roster M2."""

from __future__ import annotations

import inspect
from pathlib import Path
from uuid import uuid4

from app.api.v1.routes.organization_roster_imports import router
from app.config import Settings
from app.organization_roster_import.constants import (
    MAX_CELL_LENGTH,
    MAX_COLUMNS,
    MAX_DATA_ROWS,
    MAX_FILENAME_LENGTH,
    MAX_UPLOAD_BYTES,
    MAX_XLSX_ARCHIVE_ENTRIES,
    MAX_XLSX_UNCOMPRESSED_BYTES,
    SOURCE_RETENTION_DAYS,
)
from app.organization_roster_import.storage import build_roster_source_key
from app.repositories.organization_roster_import import OrganizationRosterImportRepository
from app.services.organization_roster_import_service import OrganizationRosterImportService

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v1_limits_and_retention_are_locked() -> None:
    assert (MAX_UPLOAD_BYTES, MAX_DATA_ROWS, MAX_COLUMNS) == (5_000_000, 10_000, 64)
    assert (MAX_CELL_LENGTH, MAX_FILENAME_LENGTH, SOURCE_RETENTION_DAYS) == (4_096, 255, 30)
    assert (MAX_XLSX_ARCHIVE_ENTRIES, MAX_XLSX_UNCOMPRESSED_BYTES) == (1_000, 100_000_000)


def test_private_storage_key_is_tenant_and_import_scoped() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        jwt_secret_key="test-jwt-secret-key-32-chars-minimum!!",
        s3_document_key_prefix="private",
    )
    organization_id = uuid4()
    import_id = uuid4()
    key = build_roster_source_key(
        settings=settings,
        organization_id=organization_id,
        import_public_id=import_id,
        filename="employees.csv",
    )
    assert key == (
        f"private/organization-rosters/organizations/{organization_id}"
        f"/imports/{import_id}/employees.csv"
    )
    assert not key.startswith("http")


def test_m2_preview_routes_remain_and_m3_adds_only_explicit_confirm() -> None:
    paths = {(route.path, tuple(sorted(route.methods or []))) for route in router.routes}
    assert {
        ("/organizations/{org_public_id}/roster-imports", ("POST",)),
        ("/organizations/{org_public_id}/roster-imports/{import_public_id}", ("GET",)),
        (
            "/organizations/{org_public_id}/roster-imports/{import_public_id}/mapping",
            ("PATCH",),
        ),
    } <= paths
    confirm_paths = [(path, methods) for path, methods in paths if "confirm" in path]
    assert confirm_paths == [
        (
            "/organizations/{org_public_id}/roster-imports/{import_public_id}/confirm",
            ("POST",),
        )
    ]


def test_service_and_repository_have_no_prohibited_cross_domain_writes() -> None:
    source = "\n".join(
        (
            inspect.getsource(OrganizationRosterImportService),
            inspect.getsource(OrganizationRosterImportRepository),
        )
    )
    prohibited_write_tokens = {
        "NotificationService(",
        "EmailDeliveryService(",
        "send_sms(",
        "TrustInvitation(",
        "VerificationRequest(",
        "Candidate(",
        "TrustScoreSnapshot(",
        "PassportShareLink(",
    }
    assert all(token not in source for token in prohibited_write_tokens)
    assert "result_organization_person_id" in source


def test_no_protected_domain_files_are_part_of_m2_source_scope() -> None:
    expected_new_modules = {
        "constants.py",
        "headers.py",
        "normalization.py",
        "parsing.py",
        "preview.py",
        "storage.py",
        "templates.py",
        "types.py",
        "application.py",
    }
    actual = {
        path.name
        for path in (REPO_ROOT / "app/organization_roster_import").glob("*.py")
        if path.name != "__init__.py" and path.name != "enums.py"
    }
    assert actual == expected_new_modules
