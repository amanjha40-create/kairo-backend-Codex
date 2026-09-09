"""Persistence-contract tests for organization roster imports."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import configure_mappers

import app.models  # noqa: F401
from app.db.base import Base
from app.models.organization import Organization
from app.models.organization_person import OrganizationPerson
from app.models.organization_person_roster_profile import OrganizationPersonRosterProfile
from app.models.organization_roster_import import (
    OrganizationRosterImport,
    OrganizationRosterImportRow,
)
from app.models.user import User
from app.organization_roster_import.enums import (
    OrganizationRosterDatePrecision,
    OrganizationRosterImportState,
    OrganizationRosterRowDisposition,
    OrganizationRosterType,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = REPO_ROOT / "alembic/versions/073_organization_roster_import_persistence.py"


def test_roster_enum_values_are_locked() -> None:
    assert {item.value for item in OrganizationRosterType} == {"employee", "student"}
    assert {item.value for item in OrganizationRosterImportState} == {
        "uploaded",
        "parsing",
        "mapping_required",
        "ready_for_review",
        "importing",
        "completed",
        "completed_with_errors",
        "failed",
    }
    assert {item.value for item in OrganizationRosterRowDisposition} == {
        "valid_new",
        "valid_update",
        "duplicate",
        "invalid",
        "skipped",
    }
    assert {item.value for item in OrganizationRosterDatePrecision} == {"year", "month", "day"}


def test_roster_tables_are_registered_in_canonical_metadata() -> None:
    assert {
        "organization_roster_imports",
        "organization_roster_import_rows",
        "organization_person_roster_profiles",
    } <= Base.metadata.tables.keys()


def test_models_construct_and_relationships_are_bidirectional() -> None:
    configure_mappers()
    organization = Organization(
        created_by_user_id=uuid4(),
        name="Roster QA Organization",
        organization_type="employer",
    )
    uploader = User(email="roster-owner@example.com", password_hash="unused", role="hr")
    roster_import = OrganizationRosterImport(
        organization=organization,
        uploaded_by=uploader,
        roster_type="employee",
        source_format="csv",
        original_filename="employees.csv",
        source_storage_key="private/organizations/import.csv",
    )
    row = OrganizationRosterImportRow(
        roster_import=roster_import,
        original_row_number=2,
        disposition="valid_new",
    )
    person = OrganizationPerson(organization=organization, full_name="Roster Person")
    profile = OrganizationPersonRosterProfile(
        organization=organization,
        organization_person=person,
        source_import=roster_import,
        imported_by=uploader,
        roster_type="employee",
        imported_at=datetime.now(tz=UTC),
        employee_id="EMP-1",
    )

    assert row in roster_import.rows
    assert profile in roster_import.sourced_profiles
    assert roster_import in organization.roster_imports
    assert profile in organization.roster_profiles
    assert person in organization.people
    assert person.roster_profile is profile
    assert roster_import in uploader.uploaded_roster_imports
    assert profile in uploader.imported_roster_profiles


def test_constraints_and_tenant_indexes_are_registered() -> None:
    import_table = OrganizationRosterImport.__table__
    row_table = OrganizationRosterImportRow.__table__
    profile_table = OrganizationPersonRosterProfile.__table__

    constraint_names = {
        constraint.name
        for table in (import_table, row_table, profile_table)
        for constraint in table.constraints
        if isinstance(constraint, (CheckConstraint, UniqueConstraint))
    }
    assert any(name.endswith("ck_roster_import_nonnegative_counts") for name in constraint_names)
    assert any(name.endswith("ck_roster_import_row_positive_number") for name in constraint_names)
    assert "uq_roster_profile_person" in constraint_names

    index_names = {
        index.name
        for table in (import_table, row_table, profile_table)
        for index in table.indexes
        if isinstance(index, Index)
    }
    assert {
        "ix_roster_import_org_state",
        "ix_roster_import_org_type",
        "ix_roster_import_row_import_disposition",
        "ix_roster_profile_org_employee_id",
        "ix_roster_profile_org_student_id",
        "ix_roster_profile_org_roll_number",
    } <= index_names


def test_foreign_key_delete_behavior_cannot_delete_people_from_import_rows() -> None:
    row_fks = {
        tuple(fk.column_keys): fk.ondelete
        for fk in OrganizationRosterImportRow.__table__.constraints
        if isinstance(fk, ForeignKeyConstraint)
    }
    assert row_fks[("import_id",)] == "CASCADE"
    assert row_fks[("matched_organization_person_id",)] == "SET NULL"
    assert row_fks[("result_organization_person_id",)] == "SET NULL"


def test_migration_is_additive_after_072() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "073"' in source
    assert 'down_revision = "072"' in source
    assert source.count("op.create_table(") == 3
    for protected_table in (
        "users",
        "organization_people",
        "organization_person_identifiers",
        "verification_requests",
        "trust_score_snapshots",
        "passport_share_links",
    ):
        assert f'op.drop_table("{protected_table}")' not in source
        assert f'op.alter_column("{protected_table}"' not in source
