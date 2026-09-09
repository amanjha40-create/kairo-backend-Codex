"""Static contracts for roster M3 routes, migration, and domain boundaries."""

from __future__ import annotations

import inspect
from pathlib import Path

from sqlalchemy import CheckConstraint, Index, UniqueConstraint

import app.models  # noqa: F401
from app.api.v1.routes.organization_roster_imports import roster_router, router
from app.db.base import Base
from app.models.organization_person_roster_profile import OrganizationPersonRosterProfile
from app.models.organization_roster_import import (
    OrganizationRosterImportAuditEvent,
    OrganizationRosterImportRow,
)
from app.organization_roster_import.application import csv_safe
from app.organization_roster_import.enums import (
    OrganizationRosterAuditAction,
    OrganizationRosterRowApplicationStatus,
)
from app.repositories.organization_roster_import import OrganizationRosterImportRepository
from app.schemas.organization_roster_import import OrganizationRosterPersonResponse
from app.services.organization_roster_import_service import OrganizationRosterImportService

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = REPO_ROOT / "alembic/versions/074_roster_confirmation_and_audit.py"


def test_m3_routes_are_explicit_and_use_organization_scoping() -> None:
    import_routes = {(route.path, frozenset(route.methods or [])) for route in router.routes}
    roster_routes = {(route.path, frozenset(route.methods or [])) for route in roster_router.routes}
    assert {
        ("/organizations/{org_public_id}/roster-imports", frozenset({"GET"})),
        (
            "/organizations/{org_public_id}/roster-imports/{import_public_id}",
            frozenset({"GET"}),
        ),
        (
            "/organizations/{org_public_id}/roster-imports/{import_public_id}/confirm",
            frozenset({"POST"}),
        ),
        (
            "/organizations/{org_public_id}/roster-imports/{import_public_id}/rows",
            frozenset({"GET"}),
        ),
        (
            "/organizations/{org_public_id}/roster-imports/{import_public_id}/errors.csv",
            frozenset({"GET"}),
        ),
    } <= import_routes
    assert roster_routes == {
        ("/organizations/{org_public_id}/roster/employees", frozenset({"GET"})),
        ("/organizations/{org_public_id}/roster/students", frozenset({"GET"})),
        (
            "/organizations/{org_public_id}/roster/templates/employee.csv",
            frozenset({"GET"}),
        ),
        (
            "/organizations/{org_public_id}/roster/templates/student.csv",
            frozenset({"GET"}),
        ),
    }


def test_m3_models_and_application_constraints_are_registered() -> None:
    assert "organization_roster_import_audit_events" in Base.metadata.tables
    row_constraints = {
        constraint.name
        for constraint in OrganizationRosterImportRow.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    audit_constraints = {
        constraint.name
        for constraint in OrganizationRosterImportAuditEvent.__table__.constraints
        if isinstance(constraint, (CheckConstraint, UniqueConstraint))
    }
    assert any(name.endswith("ck_roster_import_row_application_status") for name in row_constraints)
    assert any(name.endswith("ck_roster_import_audit_action") for name in audit_constraints)
    assert "uq_roster_import_audit_dedupe_key" in audit_constraints


def test_profile_identity_indexes_are_tenant_scoped_unique_partial_indexes() -> None:
    indexes = {index.name: index for index in OrganizationPersonRosterProfile.__table__.indexes}
    for name in (
        "ix_roster_profile_org_employee_id",
        "ix_roster_profile_org_student_id",
        "ix_roster_profile_org_roll_number",
    ):
        index = indexes[name]
        assert isinstance(index, Index)
        assert index.unique is True
        assert [column.name for column in index.columns][0] == "organization_id"
        assert index.dialect_options["postgresql"]["where"] is not None


def test_migration_074_is_additive_after_073_and_does_not_touch_protected_domains() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "074"' in source
    assert 'down_revision = "073"' in source
    assert source.count("op.create_table(") == 1
    assert '"organization_roster_import_audit_events"' in source
    assert '"application_status"' in source
    assert '"application_errors"' in source
    assert '"applied_at"' in source
    for protected_table in (
        "users",
        "employments",
        "educations",
        "verification_requests",
        "trust_score_snapshots",
        "passport_share_links",
        "notifications",
    ):
        assert f'op.alter_column("{protected_table}"' not in source
        assert f'op.drop_table("{protected_table}")' not in source


def test_confirmation_uses_lock_savepoints_and_one_success_commit_path() -> None:
    repository_source = inspect.getsource(
        OrganizationRosterImportRepository.lock_by_public_id_for_organization
    )
    confirm_source = inspect.getsource(OrganizationRosterImportService.confirm_import)
    assert ".with_for_update()" in repository_source
    assert "begin_nested()" in confirm_source
    assert "await self._session.commit()" in confirm_source
    assert "await self._session.rollback()" in confirm_source
    assert "OrganizationRosterRowDisposition.VALID_NEW" in confirm_source
    assert "OrganizationRosterRowDisposition.VALID_UPDATE" in confirm_source


def test_csv_export_cells_are_formula_safe() -> None:
    assert csv_safe("=SUM(1,1)") == "'=SUM(1,1)"
    assert csv_safe("+cmd") == "'+cmd"
    assert csv_safe("-2+3") == "'-2+3"
    assert csv_safe("@unsafe") == "'@unsafe"
    assert csv_safe("\tunsafe") == "'\tunsafe"
    assert csv_safe("  =hidden") == "'  =hidden"
    assert csv_safe("\ufeff+hidden") == "'\ufeff+hidden"
    assert csv_safe("ordinary") == "ordinary"
    assert csv_safe(None) == ""


def test_roster_response_cannot_claim_imported_people_are_verified() -> None:
    schema = OrganizationRosterPersonResponse.model_json_schema()
    assert schema["properties"]["source_status"]["const"] == "organization_provided"
    assert schema["properties"]["verified"]["const"] is False


def test_m3_enums_lock_row_outcomes_and_audit_actions() -> None:
    assert {item.value for item in OrganizationRosterRowApplicationStatus} == {
        "pending",
        "ignored",
        "created",
        "updated",
        "failed",
    }
    assert {item.value for item in OrganizationRosterAuditAction} == {
        "roster_import_confirmed",
        "roster_person_created",
        "roster_person_updated",
        "roster_import_completed",
        "roster_import_failed",
    }


def test_m3_service_has_no_cross_domain_or_messaging_side_effects() -> None:
    source = "\n".join(
        (
            inspect.getsource(OrganizationRosterImportService),
            inspect.getsource(OrganizationRosterImportRepository),
        )
    )
    prohibited = (
        "Candidate(",
        "Employment(",
        "Education(",
        "VerificationRequest(",
        "TrustScoreSnapshot(",
        "PassportShareLink(",
        "Notification(",
        "TrustInvitation(",
        "send_email(",
        "send_sms(",
        "create_outreach(",
    )
    assert all(token not in source for token in prohibited)
