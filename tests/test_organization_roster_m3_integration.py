"""PostgreSQL-backed confirmation, idempotency, and concurrency coverage for roster M3."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401
from app.config import Settings
from app.models.education import Education
from app.models.employment import Employment
from app.models.notification import Notification
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.organization_person import OrganizationPerson
from app.models.organization_person_identifier import OrganizationPersonIdentifier
from app.models.organization_person_roster_profile import OrganizationPersonRosterProfile
from app.models.organization_roster_import import (
    OrganizationRosterImport,
    OrganizationRosterImportAuditEvent,
    OrganizationRosterImportRow,
)
from app.models.user import User
from app.models.verification_request import VerificationRequest
from app.organization.enums import OrganizationRole, OrganizationType
from app.organization_people.enums import (
    OrganizationPersonIdentifierType,
    OrganizationPersonPassportStatusSummary,
    OrganizationPersonRelationship,
    OrganizationPersonTrustState,
)
from app.organization_roster_import.enums import (
    OrganizationRosterAuditAction,
    OrganizationRosterImportState,
    OrganizationRosterRowApplicationStatus,
    OrganizationRosterRowDisposition,
    OrganizationRosterType,
)
from app.schemas.organization_roster_import import (
    OrganizationRosterListQueryParams,
    RosterImportListQueryParams,
    RosterRowListQueryParams,
)
from app.services.organization_roster_import_service import OrganizationRosterImportService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]
TEST_DATABASE_URL = os.environ["DATABASE_URL"]


@pytest.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True, poolclass=NullPool)
    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
async def reset_database(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        await session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
        await session.commit()
    yield
    async with session_factory() as session:
        await session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
        await session.commit()


def _settings() -> Settings:
    return Settings(
        app_env="test",
        database_url=TEST_DATABASE_URL,
        jwt_secret_key="test-jwt-secret-key-32-chars-minimum!!",
    )


async def _seed_actor_and_org(
    session: AsyncSession,
    *,
    role: OrganizationRole = OrganizationRole.OWNER,
    organization_type: OrganizationType = OrganizationType.EMPLOYER,
) -> tuple[User, Organization]:
    actor = User(
        email=f"roster-{uuid4().hex[:10]}@kairo.test",
        full_name="Roster Owner",
        role="hr",
        is_active=True,
    )
    session.add(actor)
    await session.flush()
    organization = Organization(
        created_by_user_id=actor.id,
        name=f"Roster QA {uuid4().hex[:8]}",
        organization_type=organization_type,
    )
    session.add(organization)
    await session.flush()
    session.add(
        OrganizationMember(
            organization_id=organization.id,
            user_id=actor.id,
            role=role,
        )
    )
    await session.commit()
    return actor, organization


async def _seed_import(
    session: AsyncSession,
    *,
    actor: User,
    organization: Organization,
    roster_type: OrganizationRosterType,
    rows: list[dict[str, Any]],
    state: OrganizationRosterImportState = OrganizationRosterImportState.READY_FOR_REVIEW,
) -> OrganizationRosterImport:
    roster_import = OrganizationRosterImport(
        organization_id=organization.id,
        uploaded_by_user_id=actor.id,
        roster_type=roster_type.value,
        source_format="csv",
        original_filename="staging-qa-roster.csv",
        source_storage_key=f"private/test/{uuid4()}/roster.csv",
        state=state.value,
        total_rows=len(rows),
        valid_new_count=sum(
            row["disposition"] == OrganizationRosterRowDisposition.VALID_NEW.value for row in rows
        ),
        valid_update_count=sum(
            row["disposition"] == OrganizationRosterRowDisposition.VALID_UPDATE.value
            for row in rows
        ),
        duplicate_count=sum(
            row["disposition"] == OrganizationRosterRowDisposition.DUPLICATE.value for row in rows
        ),
        invalid_count=sum(
            row["disposition"] == OrganizationRosterRowDisposition.INVALID.value for row in rows
        ),
        skipped_count=sum(
            row["disposition"] == OrganizationRosterRowDisposition.SKIPPED.value for row in rows
        ),
        parsed_at=datetime.now(tz=UTC),
    )
    session.add(roster_import)
    await session.flush()
    session.add_all(
        [
            OrganizationRosterImportRow(
                import_id=roster_import.id,
                original_row_number=index + 2,
                source_values=row.get("source_values", row.get("normalized_values", {})),
                normalized_values=row.get("normalized_values", {}),
                disposition=row["disposition"],
                validation_errors=row.get("validation_errors", []),
                primary_identifier=row.get("primary_identifier"),
                matched_organization_person_id=row.get("matched_organization_person_id"),
            )
            for index, row in enumerate(rows)
        ]
    )
    await session.commit()
    return roster_import


async def _count(session: AsyncSession, model: type[Any]) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


@pytest.mark.parametrize(
    ("roster_type", "organization_type", "values", "profile_field", "expected_value"),
    [
        (
            OrganizationRosterType.EMPLOYEE,
            OrganizationType.EMPLOYER,
            {
                "employee_id": "EMP-001",
                "full_name": "New Employee",
                "work_email": "new.employee@example.com",
                "phone": "+919111111111",
                "department": "Engineering",
                "joining_date": "2024-01-01",
                "joining_date_precision": "year",
            },
            "employee_id",
            "EMP-001",
        ),
        (
            OrganizationRosterType.STUDENT,
            OrganizationType.UNIVERSITY,
            {
                "student_id": "STU-001",
                "roll_number": "0007",
                "full_name": "New Student",
                "institutional_email": "student@example.edu",
                "program": "Computer Science",
                "admission_date": "2023-08-01",
                "admission_date_precision": "month",
            },
            "student_id",
            "STU-001",
        ),
    ],
)
async def test_confirm_creates_employee_or_student_with_organization_only_provenance(
    session_factory: async_sessionmaker[AsyncSession],
    roster_type: OrganizationRosterType,
    organization_type: OrganizationType,
    values: dict[str, Any],
    profile_field: str,
    expected_value: str,
) -> None:
    async with session_factory() as session:
        actor, organization = await _seed_actor_and_org(
            session, organization_type=organization_type
        )
        roster_import = await _seed_import(
            session,
            actor=actor,
            organization=organization,
            roster_type=roster_type,
            rows=[
                {
                    "disposition": OrganizationRosterRowDisposition.VALID_NEW.value,
                    "normalized_values": values,
                    "primary_identifier": expected_value,
                }
            ],
        )
        response = await OrganizationRosterImportService(session, _settings()).confirm_import(
            actor_user_id=actor.id,
            org_public_id=organization.public_id,
            import_public_id=roster_import.public_id,
        )

        assert response.state is OrganizationRosterImportState.COMPLETED
        assert (response.counts.created, response.counts.updated, response.counts.failed) == (
            1,
            0,
            0,
        )
        assert response.rows[0].application_status is OrganizationRosterRowApplicationStatus.CREATED
        assert response.rows[0].result_organization_person_id is not None
        person = await session.get(
            OrganizationPerson, response.rows[0].result_organization_person_id
        )
        assert person is not None
        assert person.linked_user_id is None
        assert person.trust_state == OrganizationPersonTrustState.UNKNOWN.value
        assert (
            person.passport_status_summary
            == OrganizationPersonPassportStatusSummary.NOT_SHARED.value
        )
        profile = await session.scalar(
            select(OrganizationPersonRosterProfile).where(
                OrganizationPersonRosterProfile.organization_person_id == person.id
            )
        )
        assert profile is not None
        assert getattr(profile, profile_field) == expected_value
        assert profile.source == "organization_import"
        assert profile.source_import_id == roster_import.id
        assert profile.source_row_number == 2
        assert profile.imported_by_user_id == actor.id
        assert await _count(session, Employment) == 0
        assert await _count(session, Education) == 0
        assert await _count(session, VerificationRequest) == 0
        assert await _count(session, Notification) == 0


async def test_valid_update_preserves_blank_and_unrelated_fields(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        actor, organization = await _seed_actor_and_org(session)
        person = OrganizationPerson(
            organization_id=organization.id,
            full_name="Existing Employee",
            primary_email="existing@example.com",
            relationship=OrganizationPersonRelationship.CONTRACTOR,
            trust_state=OrganizationPersonTrustState.VERIFIED,
            passport_status_summary=OrganizationPersonPassportStatusSummary.ACTIVE,
            added_by_user_id=actor.id,
            added_at=datetime.now(tz=UTC),
        )
        session.add(person)
        await session.flush()
        session.add_all(
            [
                OrganizationPersonIdentifier(
                    organization_person_id=person.id,
                    organization_id=organization.id,
                    identifier_type=OrganizationPersonIdentifierType.EMAIL,
                    normalized_value="existing@example.com",
                    raw_value="existing@example.com",
                    is_primary=True,
                ),
                OrganizationPersonIdentifier(
                    organization_person_id=person.id,
                    organization_id=organization.id,
                    identifier_type=OrganizationPersonIdentifierType.PHONE,
                    normalized_value="+919000000009",
                    raw_value="+919000000009",
                    is_primary=True,
                ),
                OrganizationPersonRosterProfile(
                    organization_id=organization.id,
                    organization_person_id=person.id,
                    roster_type="employee",
                    source="organization_import",
                    imported_at=datetime.now(tz=UTC),
                    employee_id="EMP-009",
                    department="Keep Department",
                    designation="Old Title",
                    location="Keep Location",
                ),
            ]
        )
        await session.commit()
        roster_import = await _seed_import(
            session,
            actor=actor,
            organization=organization,
            roster_type=OrganizationRosterType.EMPLOYEE,
            rows=[
                {
                    "disposition": OrganizationRosterRowDisposition.VALID_UPDATE.value,
                    "normalized_values": {
                        "employee_id": "EMP-009",
                        "full_name": "Existing Employee Updated",
                        "work_email": "existing@example.com",
                        "phone": "+919000000010",
                        "designation": "New Title",
                    },
                    "primary_identifier": "EMP-009",
                    "matched_organization_person_id": person.id,
                }
            ],
        )
        response = await OrganizationRosterImportService(session, _settings()).confirm_import(
            actor_user_id=actor.id,
            org_public_id=organization.public_id,
            import_public_id=roster_import.public_id,
        )
        await session.refresh(person)
        profile = await session.scalar(
            select(OrganizationPersonRosterProfile).where(
                OrganizationPersonRosterProfile.organization_person_id == person.id
            )
        )
        assert response.rows[0].application_status is OrganizationRosterRowApplicationStatus.UPDATED
        assert response.counts.updated == 1
        assert person.full_name == "Existing Employee Updated"
        assert person.relationship == OrganizationPersonRelationship.CONTRACTOR.value
        assert person.primary_phone == "+919000000010"
        assert person.trust_state == OrganizationPersonTrustState.VERIFIED.value
        assert (
            person.passport_status_summary == OrganizationPersonPassportStatusSummary.ACTIVE.value
        )
        assert profile is not None
        assert profile.designation == "New Title"
        assert profile.department == "Keep Department"
        assert profile.location == "Keep Location"
        assert profile.source_import_id == roster_import.id
        identifiers = list(
            (
                await session.scalars(
                    select(OrganizationPersonIdentifier).where(
                        OrganizationPersonIdentifier.organization_person_id == person.id
                    )
                )
            ).all()
        )
        assert len(identifiers) == 3
        phone_primary = {
            identifier.normalized_value: identifier.is_primary
            for identifier in identifiers
            if str(identifier.identifier_type) == OrganizationPersonIdentifierType.PHONE.value
        }
        assert phone_primary == {
            "+919000000009": False,
            "+919000000010": True,
        }


async def test_valid_update_student_preserves_blank_fields_and_updates_provenance(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        actor, organization = await _seed_actor_and_org(
            session, organization_type=OrganizationType.UNIVERSITY
        )
        person = OrganizationPerson(
            organization_id=organization.id,
            full_name="Existing Student",
            primary_email="old.student@example.edu",
            relationship=OrganizationPersonRelationship.CANDIDATE,
            added_by_user_id=actor.id,
            added_at=datetime.now(tz=UTC),
        )
        session.add(person)
        await session.flush()
        session.add_all(
            [
                OrganizationPersonIdentifier(
                    organization_person_id=person.id,
                    organization_id=organization.id,
                    identifier_type=OrganizationPersonIdentifierType.EMAIL,
                    normalized_value="old.student@example.edu",
                    raw_value="old.student@example.edu",
                    is_primary=True,
                ),
                OrganizationPersonRosterProfile(
                    organization_id=organization.id,
                    organization_person_id=person.id,
                    roster_type="student",
                    source="organization_import",
                    imported_at=datetime.now(tz=UTC),
                    student_id="STU-009",
                    roll_number="ROLL-009",
                    degree="Keep Degree",
                    campus="Keep Campus",
                    program="Old Program",
                ),
            ]
        )
        await session.commit()
        roster_import = await _seed_import(
            session,
            actor=actor,
            organization=organization,
            roster_type=OrganizationRosterType.STUDENT,
            rows=[
                {
                    "disposition": "valid_update",
                    "normalized_values": {
                        "student_id": "STU-009",
                        "full_name": "Existing Student Updated",
                        "institutional_email": "new.student@example.edu",
                        "program": "New Program",
                    },
                    "matched_organization_person_id": person.id,
                }
            ],
        )

        response = await OrganizationRosterImportService(session, _settings()).confirm_import(
            actor_user_id=actor.id,
            org_public_id=organization.public_id,
            import_public_id=roster_import.public_id,
        )
        profile = await session.scalar(
            select(OrganizationPersonRosterProfile).where(
                OrganizationPersonRosterProfile.organization_person_id == person.id
            )
        )
        assert response.state is OrganizationRosterImportState.COMPLETED
        assert response.counts.updated == 1
        assert profile is not None
        assert profile.program == "New Program"
        assert profile.degree == "Keep Degree"
        assert profile.campus == "Keep Campus"
        assert profile.source_import_id == roster_import.id
        assert profile.source_row_number == 2
        assert person.primary_email == "new.student@example.edu"
        assert person.relationship == OrganizationPersonRelationship.CANDIDATE.value
        identifiers = list(
            (
                await session.scalars(
                    select(OrganizationPersonIdentifier).where(
                        OrganizationPersonIdentifier.organization_person_id == person.id
                    )
                )
            ).all()
        )
        assert {
            identifier.normalized_value: identifier.is_primary for identifier in identifiers
        } == {
            "old.student@example.edu": False,
            "new.student@example.edu": True,
        }


async def test_admin_can_confirm_and_nonconfirmable_state_fails_closed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from app.exceptions import ConflictError

    async with session_factory() as session:
        actor, organization = await _seed_actor_and_org(session, role=OrganizationRole.ADMIN)
        ready_import = await _seed_import(
            session,
            actor=actor,
            organization=organization,
            roster_type=OrganizationRosterType.EMPLOYEE,
            rows=[
                {
                    "disposition": "valid_new",
                    "normalized_values": {
                        "employee_id": "EMP-ADMIN",
                        "full_name": "Admin Import",
                    },
                }
            ],
        )
        result = await OrganizationRosterImportService(session, _settings()).confirm_import(
            actor_user_id=actor.id,
            org_public_id=organization.public_id,
            import_public_id=ready_import.public_id,
        )
        assert result.state is OrganizationRosterImportState.COMPLETED

        unready_import = await _seed_import(
            session,
            actor=actor,
            organization=organization,
            roster_type=OrganizationRosterType.EMPLOYEE,
            rows=[],
            state=OrganizationRosterImportState.MAPPING_REQUIRED,
        )
        with pytest.raises(ConflictError):
            await OrganizationRosterImportService(session, _settings()).confirm_import(
                actor_user_id=actor.id,
                org_public_id=organization.public_id,
                import_public_id=unready_import.public_id,
            )
        assert await _count(session, OrganizationRosterImportAuditEvent) == 3


async def test_missing_previewed_person_becomes_row_failure(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        actor, organization = await _seed_actor_and_org(session)
        person = OrganizationPerson(
            organization_id=organization.id,
            full_name="Deleted Before Confirm",
            relationship=OrganizationPersonRelationship.EMPLOYEE,
            added_by_user_id=actor.id,
        )
        session.add(person)
        await session.commit()
        roster_import = await _seed_import(
            session,
            actor=actor,
            organization=organization,
            roster_type=OrganizationRosterType.EMPLOYEE,
            rows=[
                {
                    "disposition": "valid_update",
                    "normalized_values": {
                        "employee_id": "EMP-MISSING",
                        "full_name": "Missing",
                    },
                    "matched_organization_person_id": person.id,
                }
            ],
        )
        await session.delete(person)
        await session.commit()

        response = await OrganizationRosterImportService(session, _settings()).confirm_import(
            actor_user_id=actor.id,
            org_public_id=organization.public_id,
            import_public_id=roster_import.public_id,
        )
        assert response.state is OrganizationRosterImportState.FAILED
        assert response.rows[0].application_status is OrganizationRosterRowApplicationStatus.FAILED
        assert response.rows[0].application_errors[0].code == "matched_person_missing"


async def test_same_identifier_is_allowed_in_a_different_organization(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        actor, organization = await _seed_actor_and_org(session)
        other_actor, other_organization = await _seed_actor_and_org(session)
        other_person = OrganizationPerson(
            organization_id=other_organization.id,
            full_name="Other Tenant Person",
            primary_email="shared@example.com",
            relationship=OrganizationPersonRelationship.EMPLOYEE,
            added_by_user_id=other_actor.id,
        )
        session.add(other_person)
        await session.flush()
        session.add(
            OrganizationPersonIdentifier(
                organization_person_id=other_person.id,
                organization_id=other_organization.id,
                identifier_type=OrganizationPersonIdentifierType.EMAIL,
                normalized_value="shared@example.com",
                raw_value="shared@example.com",
            )
        )
        await session.commit()
        roster_import = await _seed_import(
            session,
            actor=actor,
            organization=organization,
            roster_type=OrganizationRosterType.EMPLOYEE,
            rows=[
                {
                    "disposition": "valid_new",
                    "normalized_values": {
                        "employee_id": "EMP-SHARED",
                        "full_name": "Own Tenant Person",
                        "work_email": "shared@example.com",
                    },
                }
            ],
        )
        response = await OrganizationRosterImportService(session, _settings()).confirm_import(
            actor_user_id=actor.id,
            org_public_id=organization.public_id,
            import_public_id=roster_import.public_id,
        )
        assert response.state is OrganizationRosterImportState.COMPLETED
        assert await _count(session, OrganizationPerson) == 2


async def test_confirm_rejects_name_only_row_even_if_ledger_was_tampered(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        actor, organization = await _seed_actor_and_org(session)
        roster_import = await _seed_import(
            session,
            actor=actor,
            organization=organization,
            roster_type=OrganizationRosterType.EMPLOYEE,
            rows=[
                {
                    "disposition": "valid_new",
                    "normalized_values": {"full_name": "Name Alone"},
                }
            ],
        )
        response = await OrganizationRosterImportService(session, _settings()).confirm_import(
            actor_user_id=actor.id,
            org_public_id=organization.public_id,
            import_public_id=roster_import.public_id,
        )
        assert response.state is OrganizationRosterImportState.FAILED
        assert response.rows[0].application_errors[0].code == "identifier_required"
        assert await _count(session, OrganizationPerson) == 0


async def test_confirm_rejects_stale_update_when_identity_no_longer_resolves(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        actor, organization = await _seed_actor_and_org(session)
        person = OrganizationPerson(
            organization_id=organization.id,
            full_name="Stale Match",
            relationship=OrganizationPersonRelationship.EMPLOYEE,
            added_by_user_id=actor.id,
        )
        session.add(person)
        await session.flush()
        profile = OrganizationPersonRosterProfile(
            organization_id=organization.id,
            organization_person_id=person.id,
            roster_type="employee",
            source="organization_import",
            imported_at=datetime.now(tz=UTC),
            employee_id="EMP-OLD",
        )
        session.add(profile)
        await session.commit()
        roster_import = await _seed_import(
            session,
            actor=actor,
            organization=organization,
            roster_type=OrganizationRosterType.EMPLOYEE,
            rows=[
                {
                    "disposition": "valid_update",
                    "normalized_values": {
                        "employee_id": "EMP-OLD",
                        "full_name": "Must Not Apply",
                    },
                    "matched_organization_person_id": person.id,
                }
            ],
        )
        profile.employee_id = "EMP-CHANGED-AFTER-PREVIEW"
        await session.commit()

        response = await OrganizationRosterImportService(session, _settings()).confirm_import(
            actor_user_id=actor.id,
            org_public_id=organization.public_id,
            import_public_id=roster_import.public_id,
        )
        await session.refresh(person)
        assert response.state is OrganizationRosterImportState.FAILED
        assert response.rows[0].application_errors[0].code == "matched_person_changed"
        assert person.full_name == "Stale Match"


async def test_partial_success_ignores_non_applicable_rows_and_records_stale_conflict(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        actor, organization = await _seed_actor_and_org(session)
        existing = OrganizationPerson(
            organization_id=organization.id,
            full_name="Conflict Owner",
            primary_email="conflict@example.com",
            relationship="employee",
            added_by_user_id=actor.id,
            added_at=datetime.now(tz=UTC),
        )
        session.add(existing)
        await session.flush()
        session.add(
            OrganizationPersonIdentifier(
                organization_person_id=existing.id,
                organization_id=organization.id,
                identifier_type=OrganizationPersonIdentifierType.EMAIL,
                normalized_value="conflict@example.com",
                raw_value="conflict@example.com",
                is_primary=True,
            )
        )
        await session.commit()
        roster_import = await _seed_import(
            session,
            actor=actor,
            organization=organization,
            roster_type=OrganizationRosterType.EMPLOYEE,
            rows=[
                {
                    "disposition": OrganizationRosterRowDisposition.VALID_NEW.value,
                    "normalized_values": {
                        "employee_id": "EMP-NEW",
                        "full_name": "Safe New Person",
                        "work_email": "safe@example.com",
                    },
                },
                {
                    "disposition": OrganizationRosterRowDisposition.VALID_NEW.value,
                    "normalized_values": {
                        "employee_id": "EMP-CONFLICT",
                        "full_name": "Stale Preview",
                        "work_email": "conflict@example.com",
                    },
                },
                {"disposition": OrganizationRosterRowDisposition.DUPLICATE.value},
                {
                    "disposition": OrganizationRosterRowDisposition.INVALID.value,
                    "validation_errors": [
                        {
                            "code": "invalid_email",
                            "field": "work_email",
                            "message": "Email address is invalid",
                            "row_number": 5,
                        }
                    ],
                },
                {"disposition": OrganizationRosterRowDisposition.SKIPPED.value},
            ],
        )
        response = await OrganizationRosterImportService(session, _settings()).confirm_import(
            actor_user_id=actor.id,
            org_public_id=organization.public_id,
            import_public_id=roster_import.public_id,
        )
        assert response.state is OrganizationRosterImportState.COMPLETED_WITH_ERRORS
        assert (response.counts.created, response.counts.failed) == (1, 1)
        assert [row.application_status.value for row in response.rows] == [
            "created",
            "failed",
            "ignored",
            "ignored",
            "ignored",
        ]
        assert response.rows[1].application_errors[0].code == "identifier_conflict"
        assert await _count(session, OrganizationPerson) == 2


async def test_all_applicable_rows_failing_finalizes_failed_without_partial_person(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        actor, organization = await _seed_actor_and_org(session)
        existing = OrganizationPerson(
            organization_id=organization.id,
            full_name="Existing",
            primary_email="taken@example.com",
            relationship="employee",
            added_by_user_id=actor.id,
            added_at=datetime.now(tz=UTC),
        )
        session.add(existing)
        await session.flush()
        session.add(
            OrganizationPersonIdentifier(
                organization_person_id=existing.id,
                organization_id=organization.id,
                identifier_type=OrganizationPersonIdentifierType.EMAIL,
                normalized_value="taken@example.com",
                raw_value="taken@example.com",
            )
        )
        await session.commit()
        roster_import = await _seed_import(
            session,
            actor=actor,
            organization=organization,
            roster_type=OrganizationRosterType.EMPLOYEE,
            rows=[
                {
                    "disposition": "valid_new",
                    "normalized_values": {
                        "employee_id": "EMP-X",
                        "full_name": "Conflict",
                        "work_email": "taken@example.com",
                    },
                }
            ],
        )
        response = await OrganizationRosterImportService(session, _settings()).confirm_import(
            actor_user_id=actor.id,
            org_public_id=organization.public_id,
            import_public_id=roster_import.public_id,
        )
        assert response.state is OrganizationRosterImportState.FAILED
        assert response.failure_code == "no_rows_applied"
        assert response.counts.failed == 1
        assert await _count(session, OrganizationPerson) == 1


async def test_unexpected_row_error_is_sanitized_and_does_not_corrupt_registry(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with session_factory() as session:
        actor, organization = await _seed_actor_and_org(session)
        roster_import = await _seed_import(
            session,
            actor=actor,
            organization=organization,
            roster_type=OrganizationRosterType.EMPLOYEE,
            rows=[
                {
                    "disposition": "valid_new",
                    "normalized_values": {
                        "employee_id": "EMP-ROW-ERROR",
                        "full_name": "Never Persisted",
                    },
                }
            ],
        )
        service = OrganizationRosterImportService(session, _settings())

        async def fail_row(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("database details must not reach clients")

        monkeypatch.setattr(service, "_apply_row", fail_row)
        response = await service.confirm_import(
            actor_user_id=actor.id,
            org_public_id=organization.public_id,
            import_public_id=roster_import.public_id,
        )
        assert response.state is OrganizationRosterImportState.FAILED
        assert response.rows[0].application_errors[0].code == "row_application_failed"
        assert response.rows[0].application_errors[0].message == (
            "The row could not be applied safely"
        )
        assert "database details" not in str(response.rows[0].application_errors)
        assert await _count(session, OrganizationPerson) == 0


async def test_terminal_audit_failure_rolls_back_applied_rows_and_finalizes_failed(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with session_factory() as session:
        actor, organization = await _seed_actor_and_org(session)
        roster_import = await _seed_import(
            session,
            actor=actor,
            organization=organization,
            roster_type=OrganizationRosterType.EMPLOYEE,
            rows=[
                {
                    "disposition": "valid_new",
                    "normalized_values": {
                        "employee_id": "EMP-ROLLBACK",
                        "full_name": "Rolled Back",
                    },
                }
            ],
        )
        service = OrganizationRosterImportService(session, _settings())
        append_audit = service._repository.append_audit

        async def fail_completion(event: OrganizationRosterImportAuditEvent):
            if event.action == OrganizationRosterAuditAction.IMPORT_COMPLETED.value:
                raise RuntimeError("terminal audit unavailable")
            return await append_audit(event)

        monkeypatch.setattr(service._repository, "append_audit", fail_completion)
        with pytest.raises(RuntimeError, match="terminal audit unavailable"):
            await service.confirm_import(
                actor_user_id=actor.id,
                org_public_id=organization.public_id,
                import_public_id=roster_import.public_id,
            )

        persisted_import = await session.scalar(
            select(OrganizationRosterImport).where(OrganizationRosterImport.id == roster_import.id)
        )
        assert persisted_import is not None
        assert persisted_import.state == OrganizationRosterImportState.FAILED.value
        assert persisted_import.failure_code == "confirmation_failed"
        assert await _count(session, OrganizationPerson) == 0
        events = list((await session.scalars(select(OrganizationRosterImportAuditEvent))).all())
        assert [event.action for event in events] == [
            OrganizationRosterAuditAction.IMPORT_FAILED.value
        ]


async def test_repeat_confirm_is_idempotent_and_does_not_duplicate_any_records(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        actor, organization = await _seed_actor_and_org(session)
        roster_import = await _seed_import(
            session,
            actor=actor,
            organization=organization,
            roster_type=OrganizationRosterType.EMPLOYEE,
            rows=[
                {
                    "disposition": "valid_new",
                    "normalized_values": {
                        "employee_id": "EMP-IDEMPOTENT",
                        "full_name": "One Person",
                        "work_email": "one@example.com",
                    },
                }
            ],
        )
        service = OrganizationRosterImportService(session, _settings())
        first = await service.confirm_import(
            actor_user_id=actor.id,
            org_public_id=organization.public_id,
            import_public_id=roster_import.public_id,
        )
        second = await service.confirm_import(
            actor_user_id=actor.id,
            org_public_id=organization.public_id,
            import_public_id=roster_import.public_id,
        )
        assert second == first
        assert await _count(session, OrganizationPerson) == 1
        assert await _count(session, OrganizationPersonIdentifier) == 1
        assert await _count(session, OrganizationPersonRosterProfile) == 1
        assert await _count(session, OrganizationRosterImportAuditEvent) == 3


async def test_later_import_updates_latest_provenance_without_erasing_prior_lineage(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        actor, organization = await _seed_actor_and_org(session)
        first_import = await _seed_import(
            session,
            actor=actor,
            organization=organization,
            roster_type=OrganizationRosterType.EMPLOYEE,
            rows=[
                {
                    "disposition": "valid_new",
                    "normalized_values": {
                        "employee_id": "EMP-LINEAGE",
                        "full_name": "Before Update",
                    },
                }
            ],
        )
        service = OrganizationRosterImportService(session, _settings())
        first_result = await service.confirm_import(
            actor_user_id=actor.id,
            org_public_id=organization.public_id,
            import_public_id=first_import.public_id,
        )
        person_id = first_result.rows[0].result_organization_person_id
        assert person_id is not None
        second_import = await _seed_import(
            session,
            actor=actor,
            organization=organization,
            roster_type=OrganizationRosterType.EMPLOYEE,
            rows=[
                {
                    "disposition": "valid_update",
                    "normalized_values": {
                        "employee_id": "EMP-LINEAGE",
                        "full_name": "After Update",
                    },
                    "matched_organization_person_id": person_id,
                }
            ],
        )
        second_result = await service.confirm_import(
            actor_user_id=actor.id,
            org_public_id=organization.public_id,
            import_public_id=second_import.public_id,
        )
        profile = await session.scalar(
            select(OrganizationPersonRosterProfile).where(
                OrganizationPersonRosterProfile.organization_person_id == person_id
            )
        )
        first_row = await session.scalar(
            select(OrganizationRosterImportRow).where(
                OrganizationRosterImportRow.import_id == first_import.id
            )
        )
        assert (
            second_result.rows[0].application_status
            is OrganizationRosterRowApplicationStatus.UPDATED
        )
        assert profile is not None and profile.source_import_id == second_import.id
        assert first_row is not None
        assert first_row.result_organization_person_id == person_id
        assert first_row.normalized_values["full_name"] == "Before Update"
        assert await _count(session, OrganizationRosterImportAuditEvent) == 6


async def test_two_concurrent_confirms_apply_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as seed_session:
        actor, organization = await _seed_actor_and_org(seed_session)
        roster_import = await _seed_import(
            seed_session,
            actor=actor,
            organization=organization,
            roster_type=OrganizationRosterType.EMPLOYEE,
            rows=[
                {
                    "disposition": "valid_new",
                    "normalized_values": {
                        "employee_id": "EMP-CONCURRENT",
                        "full_name": "Concurrent Person",
                        "work_email": "concurrent@example.com",
                    },
                }
            ],
        )
        actor_id = actor.id
        org_public_id = organization.public_id
        import_public_id = roster_import.public_id

    async def _confirm() -> tuple[str, int]:
        async with session_factory() as session:
            response = await OrganizationRosterImportService(session, _settings()).confirm_import(
                actor_user_id=actor_id,
                org_public_id=org_public_id,
                import_public_id=import_public_id,
            )
            return response.state.value, response.counts.created

    results = await asyncio.gather(_confirm(), _confirm())
    assert results == [("completed", 1), ("completed", 1)]
    async with session_factory() as assertion_session:
        assert await _count(assertion_session, OrganizationPerson) == 1
        assert await _count(assertion_session, OrganizationPersonIdentifier) == 1
        assert await _count(assertion_session, OrganizationPersonRosterProfile) == 1
        assert await _count(assertion_session, OrganizationRosterImportAuditEvent) == 3


async def test_history_rows_roster_and_error_report_are_scoped_and_safe(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        actor, organization = await _seed_actor_and_org(session)
        other_actor, other_organization = await _seed_actor_and_org(session)
        roster_import = await _seed_import(
            session,
            actor=actor,
            organization=organization,
            roster_type=OrganizationRosterType.EMPLOYEE,
            rows=[
                {
                    "disposition": "valid_new",
                    "normalized_values": {
                        "employee_id": "EMP-LIST",
                        "full_name": "Listed Person",
                        "work_email": "listed@example.com",
                    },
                },
                {
                    "disposition": "invalid",
                    "primary_identifier": '=HYPERLINK("bad")',
                    "validation_errors": [
                        {
                            "code": "+FORMULA",
                            "field": None,
                            "message": "@unsafe message",
                            "row_number": 3,
                        }
                    ],
                },
            ],
        )
        await _seed_import(
            session,
            actor=other_actor,
            organization=other_organization,
            roster_type=OrganizationRosterType.EMPLOYEE,
            rows=[{"disposition": "invalid"}],
        )
        service = OrganizationRosterImportService(session, _settings())
        await service.confirm_import(
            actor_user_id=actor.id,
            org_public_id=organization.public_id,
            import_public_id=roster_import.public_id,
        )
        history = await service.list_imports(
            actor_user_id=actor.id,
            org_public_id=organization.public_id,
            params=RosterImportListQueryParams(page=1, page_size=10, roster_type="employee"),
        )
        row_page = await service.list_import_rows(
            actor_user_id=actor.id,
            org_public_id=organization.public_id,
            import_public_id=roster_import.public_id,
            params=RosterRowListQueryParams(page=1, page_size=1),
        )
        roster = await service.list_roster(
            actor_user_id=actor.id,
            org_public_id=organization.public_id,
            roster_type=OrganizationRosterType.EMPLOYEE,
            params=OrganizationRosterListQueryParams(page=1, page_size=10),
        )
        filename, report = await service.build_error_report(
            actor_user_id=actor.id,
            org_public_id=organization.public_id,
            import_public_id=roster_import.public_id,
        )
        assert history.total == 1
        assert row_page.total == 2 and len(row_page.items) == 1
        assert roster.total == 1
        assert roster.items[0].source_status == "organization_provided"
        assert roster.items[0].verified is False
        assert roster.items[0].source_import_id == roster_import.public_id
        assert filename.endswith("-errors.csv")
        assert "'=HYPERLINK" in report
        assert "'+FORMULA" in report
        assert "'@unsafe message" in report


async def test_normal_member_and_cross_organization_access_are_denied(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from app.exceptions import ForbiddenError, NotFoundError

    async with session_factory() as session:
        member, organization = await _seed_actor_and_org(session, role=OrganizationRole.MEMBER)
        owner, other_organization = await _seed_actor_and_org(session)
        roster_import = await _seed_import(
            session,
            actor=owner,
            organization=other_organization,
            roster_type=OrganizationRosterType.EMPLOYEE,
            rows=[{"disposition": "invalid"}],
        )
        session.add(
            OrganizationMember(
                organization_id=organization.id,
                user_id=owner.id,
                role=OrganizationRole.ADMIN,
            )
        )
        await session.commit()
        service = OrganizationRosterImportService(session, _settings())
        with pytest.raises(ForbiddenError):
            await service.list_imports(
                actor_user_id=member.id,
                org_public_id=organization.public_id,
                params=RosterImportListQueryParams(),
            )
        with pytest.raises(NotFoundError):
            await service.get_preview(
                actor_user_id=owner.id,
                org_public_id=other_organization.public_id,
                import_public_id=uuid4(),
            )
        with pytest.raises(NotFoundError):
            await service.get_preview(
                actor_user_id=owner.id,
                org_public_id=organization.public_id,
                import_public_id=roster_import.public_id,
            )


async def test_audit_metadata_is_deduplicated_and_contains_no_uploaded_pii(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        actor, organization = await _seed_actor_and_org(session)
        roster_import = await _seed_import(
            session,
            actor=actor,
            organization=organization,
            roster_type=OrganizationRosterType.EMPLOYEE,
            rows=[
                {
                    "disposition": "valid_new",
                    "normalized_values": {
                        "employee_id": "EMP-AUDIT",
                        "full_name": "Sensitive Name",
                        "work_email": "sensitive@example.com",
                    },
                }
            ],
        )
        await OrganizationRosterImportService(session, _settings()).confirm_import(
            actor_user_id=actor.id,
            org_public_id=organization.public_id,
            import_public_id=roster_import.public_id,
        )
        events = list(
            (
                await session.scalars(
                    select(OrganizationRosterImportAuditEvent).order_by(
                        OrganizationRosterImportAuditEvent.created_at
                    )
                )
            ).all()
        )
        assert [event.action for event in events] == [
            "roster_import_confirmed",
            "roster_person_created",
            "roster_import_completed",
        ]
        assert len({event.dedupe_key for event in events}) == 3
        rendered = str([event.metadata_payload for event in events])
        assert "Sensitive Name" not in rendered
        assert "sensitive@example.com" not in rendered
