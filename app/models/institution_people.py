"""Institution-owned academic people projections and credential history."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
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
from app.institution_people.enums import (
    InstitutionCredentialStatus,
    InstitutionVerificationStatus,
)

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.organization_person import OrganizationPerson
    from app.models.user import User


class InstitutionPersonProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "institution_person_profiles"
    __table_args__ = (
        UniqueConstraint("organization_person_id", name="uq_institution_person_profiles_person"),
        UniqueConstraint(
            "organization_id", "student_id", name="uq_institution_person_profiles_student_id"
        ),
    )

    public_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False
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
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    student_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    degree: Mapped[str | None] = mapped_column(String(255), nullable=True)
    programme: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    admission_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    admission_period: Mapped[str | None] = mapped_column(String(32), nullable=True)
    graduation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    graduation_period: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    institution_verification_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=InstitutionVerificationStatus.NOT_STARTED.value,
        server_default=InstitutionVerificationStatus.NOT_STARTED.value,
        index=True,
    )
    status_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    status_changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    organization: Mapped["Organization"] = relationship("Organization")
    organization_person: Mapped["OrganizationPerson"] = relationship("OrganizationPerson")
    status_changed_by: Mapped["User | None"] = relationship("User")
    lifecycle_events: Mapped[list["InstitutionPersonLifecycleEvent"]] = relationship(
        "InstitutionPersonLifecycleEvent",
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="InstitutionPersonLifecycleEvent.created_at.asc()",
    )
    credentials: Mapped[list["OrganizationCredentialRecord"]] = relationship(
        "OrganizationCredentialRecord",
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="OrganizationCredentialRecord.created_at.desc()",
    )


class InstitutionPersonLifecycleEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "institution_person_lifecycle_events"

    public_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("institution_person_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    previous_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False, index=True
    )

    profile: Mapped["InstitutionPersonProfile"] = relationship(
        "InstitutionPersonProfile", back_populates="lifecycle_events"
    )
    actor: Mapped["User | None"] = relationship("User")


class OrganizationCredentialRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization_credential_records"

    public_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False
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
    profile_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("institution_person_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    credential_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    degree: Mapped[str | None] = mapped_column(String(255), nullable=True)
    programme: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issued_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    issued_period: Mapped[str | None] = mapped_column(String(32), nullable=True)
    credential_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=InstitutionCredentialStatus.ISSUED.value,
        server_default=InstitutionCredentialStatus.ISSUED.value,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    organization: Mapped["Organization"] = relationship("Organization")
    organization_person: Mapped["OrganizationPerson"] = relationship("OrganizationPerson")
    profile: Mapped["InstitutionPersonProfile"] = relationship(
        "InstitutionPersonProfile", back_populates="credentials"
    )
    events: Mapped[list["OrganizationCredentialEvent"]] = relationship(
        "OrganizationCredentialEvent",
        back_populates="credential",
        cascade="all, delete-orphan",
        order_by="OrganizationCredentialEvent.created_at.asc()",
    )


class OrganizationCredentialEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "organization_credential_events"

    public_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False
    )
    credential_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organization_credential_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False, index=True
    )

    credential: Mapped["OrganizationCredentialRecord"] = relationship(
        "OrganizationCredentialRecord", back_populates="events"
    )
    actor: Mapped["User | None"] = relationship("User")


class InstitutionPersonConsent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "institution_person_consents"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "organization_person_id", name="uq_institution_person_consents_scope"
        ),
    )

    public_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False
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
    subject_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    allowed_fields: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    consent_version: Mapped[str] = mapped_column(String(64), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
