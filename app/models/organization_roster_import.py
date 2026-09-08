"""Organization-owned ledgers for preview-first roster imports."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.organization_roster_import.enums import (
    OrganizationRosterAuditAction,
    OrganizationRosterImportState,
    OrganizationRosterRowApplicationStatus,
    OrganizationRosterRowDisposition,
)

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.organization_person import OrganizationPerson
    from app.models.organization_person_roster_profile import OrganizationPersonRosterProfile
    from app.models.user import User


class OrganizationRosterImport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization_roster_imports"
    __table_args__ = (
        CheckConstraint("roster_type IN ('employee', 'student')", name="ck_roster_import_type"),
        CheckConstraint("source_format IN ('csv', 'xlsx')", name="ck_roster_import_source_format"),
        CheckConstraint(
            "state IN ('uploaded', 'parsing', 'mapping_required', 'ready_for_review', "
            "'importing', 'completed', 'completed_with_errors', 'failed')",
            name="ck_roster_import_state",
        ),
        CheckConstraint(
            "total_rows >= 0 AND valid_new_count >= 0 AND valid_update_count >= 0 "
            "AND duplicate_count >= 0 AND invalid_count >= 0 AND skipped_count >= 0 "
            "AND created_count >= 0 AND updated_count >= 0 AND failed_count >= 0",
            name="ck_roster_import_nonnegative_counts",
        ),
        Index("ix_roster_import_org_state", "organization_id", "state"),
        Index("ix_roster_import_org_type", "organization_id", "roster_type"),
    )

    public_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), default=uuid.uuid4, nullable=False, unique=True, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    roster_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source_format: Mapped[str] = mapped_column(String(8), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=OrganizationRosterImportState.UPLOADED.value,
        server_default=OrganizationRosterImportState.UPLOADED.value,
        index=True,
    )
    source_sheet_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_sheet_warning: Mapped[str | None] = mapped_column(String(512), nullable=True)
    column_mapping: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    warnings: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    valid_new_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    valid_update_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    duplicate_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    invalid_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    skipped_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    updated_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    failed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="roster_imports"
    )
    uploaded_by: Mapped["User"] = relationship(
        "User", foreign_keys=[uploaded_by_user_id], back_populates="uploaded_roster_imports"
    )
    rows: Mapped[list["OrganizationRosterImportRow"]] = relationship(
        "OrganizationRosterImportRow", back_populates="roster_import", cascade="all, delete-orphan"
    )
    sourced_profiles: Mapped[list["OrganizationPersonRosterProfile"]] = relationship(
        "OrganizationPersonRosterProfile", back_populates="source_import"
    )
    audit_events: Mapped[list["OrganizationRosterImportAuditEvent"]] = relationship(
        "OrganizationRosterImportAuditEvent",
        back_populates="roster_import",
        cascade="all, delete-orphan",
        order_by="OrganizationRosterImportAuditEvent.created_at.asc()",
    )


class OrganizationRosterImportRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization_roster_import_rows"
    __table_args__ = (
        UniqueConstraint("import_id", "original_row_number", name="uq_roster_import_row_number"),
        CheckConstraint("original_row_number > 0", name="ck_roster_import_row_positive_number"),
        CheckConstraint(
            "disposition IN ('valid_new', 'valid_update', 'duplicate', 'invalid', 'skipped')",
            name="ck_roster_import_row_disposition",
        ),
        CheckConstraint(
            "application_status IN ('pending', 'ignored', 'created', 'updated', 'failed')",
            name="ck_roster_import_row_application_status",
        ),
        Index("ix_roster_import_row_import_disposition", "import_id", "disposition"),
        Index(
            "ix_roster_import_row_import_application_status",
            "import_id",
            "application_status",
        ),
    )

    import_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organization_roster_imports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_values: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    normalized_values: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    disposition: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=OrganizationRosterRowDisposition.INVALID.value,
        server_default=OrganizationRosterRowDisposition.INVALID.value,
        index=True,
    )
    validation_errors: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    application_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=OrganizationRosterRowApplicationStatus.PENDING.value,
        server_default=OrganizationRosterRowApplicationStatus.PENDING.value,
        index=True,
    )
    application_errors: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    primary_identifier: Mapped[str | None] = mapped_column(String(320), nullable=True)
    matched_organization_person_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organization_people.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    result_organization_person_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organization_people.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    roster_import: Mapped["OrganizationRosterImport"] = relationship(
        "OrganizationRosterImport", back_populates="rows"
    )
    matched_organization_person: Mapped["OrganizationPerson | None"] = relationship(
        "OrganizationPerson",
        foreign_keys=[matched_organization_person_id],
        back_populates="matched_roster_import_rows",
    )
    result_organization_person: Mapped["OrganizationPerson | None"] = relationship(
        "OrganizationPerson",
        foreign_keys=[result_organization_person_id],
        back_populates="result_roster_import_rows",
    )


class OrganizationRosterImportAuditEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only, PII-minimized audit trail for roster confirmation."""

    __tablename__ = "organization_roster_import_audit_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('roster_import_confirmed', 'roster_person_created', "
            "'roster_person_updated', 'roster_import_completed', 'roster_import_failed')",
            name="ck_roster_import_audit_action",
        ),
        UniqueConstraint("dedupe_key", name="uq_roster_import_audit_dedupe_key"),
        Index("ix_roster_import_audit_import_created", "import_id", "created_at"),
        Index("ix_roster_import_audit_org_created", "organization_id", "created_at"),
    )

    public_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), default=uuid.uuid4, nullable=False, unique=True, index=True
    )
    import_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organization_roster_imports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    organization_person_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organization_people.id", ondelete="SET NULL"),
        nullable=True,
    )
    row_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organization_roster_import_rows.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(
        String(40), nullable=False, default=OrganizationRosterAuditAction.IMPORT_CONFIRMED.value
    )
    dedupe_key: Mapped[str] = mapped_column(String(160), nullable=False)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), index=True
    )

    roster_import: Mapped["OrganizationRosterImport"] = relationship(
        "OrganizationRosterImport", back_populates="audit_events"
    )
