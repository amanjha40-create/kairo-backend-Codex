"""Organization-provided roster details and source provenance."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.organization_person import OrganizationPerson
    from app.models.organization_roster_import import OrganizationRosterImport
    from app.models.user import User


class OrganizationPersonRosterProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization_person_roster_profiles"
    __table_args__ = (
        UniqueConstraint("organization_person_id", name="uq_roster_profile_person"),
        CheckConstraint("roster_type IN ('employee', 'student')", name="ck_roster_profile_type"),
        CheckConstraint("source = 'organization_import'", name="ck_roster_profile_source"),
        CheckConstraint(
            "source_row_number IS NULL OR source_row_number > 0",
            name="ck_roster_profile_source_row",
        ),
        CheckConstraint(
            "joining_date_precision IS NULL OR joining_date_precision IN ('year', 'month', 'day')",
            name="ck_roster_profile_joining_precision",
        ),
        CheckConstraint(
            "exit_date_precision IS NULL OR exit_date_precision IN ('year', 'month', 'day')",
            name="ck_roster_profile_exit_precision",
        ),
        CheckConstraint(
            "admission_date_precision IS NULL "
            "OR admission_date_precision IN ('year', 'month', 'day')",
            name="ck_roster_profile_admission_precision",
        ),
        CheckConstraint(
            "graduation_date_precision IS NULL "
            "OR graduation_date_precision IN ('year', 'month', 'day')",
            name="ck_roster_profile_graduation_precision",
        ),
        Index("ix_roster_profile_org_type", "organization_id", "roster_type"),
        Index(
            "ix_roster_profile_org_employee_id",
            "organization_id",
            "employee_id",
            unique=True,
            postgresql_where=text("employee_id IS NOT NULL"),
        ),
        Index(
            "ix_roster_profile_org_student_id",
            "organization_id",
            "student_id",
            unique=True,
            postgresql_where=text("student_id IS NOT NULL"),
        ),
        Index(
            "ix_roster_profile_org_roll_number",
            "organization_id",
            "roll_number",
            unique=True,
            postgresql_where=text("roll_number IS NOT NULL"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_person_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organization_people.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    roster_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="organization_import",
        server_default="organization_import",
    )
    source_import_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organization_roster_imports.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    imported_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    employee_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    student_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    roll_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    designation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    joining_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    joining_date_precision: Mapped[str | None] = mapped_column(String(8), nullable=True)
    exit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    exit_date_precision: Mapped[str | None] = mapped_column(String(8), nullable=True)
    employment_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    degree: Mapped[str | None] = mapped_column(String(255), nullable=True)
    program: Mapped[str | None] = mapped_column(String(255), nullable=True)
    specialization: Mapped[str | None] = mapped_column(String(255), nullable=True)
    admission_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    admission_date_precision: Mapped[str | None] = mapped_column(String(8), nullable=True)
    graduation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    graduation_date_precision: Mapped[str | None] = mapped_column(String(8), nullable=True)
    enrollment_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    campus: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cohort: Mapped[str | None] = mapped_column(String(128), nullable=True)

    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="roster_profiles"
    )
    organization_person: Mapped["OrganizationPerson"] = relationship(
        "OrganizationPerson", back_populates="roster_profile"
    )
    source_import: Mapped["OrganizationRosterImport | None"] = relationship(
        "OrganizationRosterImport", back_populates="sourced_profiles"
    )
    imported_by: Mapped["User | None"] = relationship(
        "User", foreign_keys=[imported_by_user_id], back_populates="imported_roster_profiles"
    )
