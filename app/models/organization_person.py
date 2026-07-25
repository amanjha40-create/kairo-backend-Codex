"""Canonical organization-scoped person model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship as orm_relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.pg_enums import (
    organization_person_invitation_status_summary_enum,
    organization_person_lifecycle_status_enum,
    organization_person_passport_status_summary_enum,
    organization_person_relationship_enum,
    organization_person_trust_state_enum,
    organization_person_verification_status_summary_enum,
)
from app.organization_people.enums import (
    OrganizationPersonInvitationStatusSummary,
    OrganizationPersonLifecycleStatus,
    OrganizationPersonPassportStatusSummary,
    OrganizationPersonRelationship,
    OrganizationPersonTrustState,
    OrganizationPersonVerificationStatusSummary,
)

if TYPE_CHECKING:
    from app.models.employment import Employment
    from app.models.organization import Organization
    from app.models.organization_person_identifier import OrganizationPersonIdentifier
    from app.models.organization_person_note import OrganizationPersonNote
    from app.models.organization_person_passport_access import OrganizationPersonPassportAccess
    from app.models.trust_invitation import TrustInvitation
    from app.models.user import User
    from app.models.verification_request import VerificationRequest


class OrganizationPerson(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Canonical organization-scoped person record."""

    __tablename__ = "organization_people"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "linked_user_id",
            name="uq_organization_people_organization_id_linked_user_id",
        ),
    )

    public_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    linked_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    primary_email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    primary_phone: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    relationship: Mapped[OrganizationPersonRelationship] = mapped_column(
        organization_person_relationship_enum,
        nullable=False,
        default=OrganizationPersonRelationship.CANDIDATE,
        server_default=OrganizationPersonRelationship.CANDIDATE.value,
    )
    lifecycle_status: Mapped[OrganizationPersonLifecycleStatus] = mapped_column(
        organization_person_lifecycle_status_enum,
        nullable=False,
        default=OrganizationPersonLifecycleStatus.ACTIVE,
        server_default=OrganizationPersonLifecycleStatus.ACTIVE.value,
        index=True,
    )
    trust_state: Mapped[OrganizationPersonTrustState] = mapped_column(
        organization_person_trust_state_enum,
        nullable=False,
        default=OrganizationPersonTrustState.UNKNOWN,
        server_default=OrganizationPersonTrustState.UNKNOWN.value,
        index=True,
    )
    invitation_status_summary: Mapped[OrganizationPersonInvitationStatusSummary] = mapped_column(
        organization_person_invitation_status_summary_enum,
        nullable=False,
        default=OrganizationPersonInvitationStatusSummary.NOT_INVITED,
        server_default=OrganizationPersonInvitationStatusSummary.NOT_INVITED.value,
        index=True,
    )
    verification_status_summary: Mapped[OrganizationPersonVerificationStatusSummary] = mapped_column(
        organization_person_verification_status_summary_enum,
        nullable=False,
        default=OrganizationPersonVerificationStatusSummary.NOT_STARTED,
        server_default=OrganizationPersonVerificationStatusSummary.NOT_STARTED.value,
        index=True,
    )
    passport_status_summary: Mapped[OrganizationPersonPassportStatusSummary] = mapped_column(
        organization_person_passport_status_summary_enum,
        nullable=False,
        default=OrganizationPersonPassportStatusSummary.NOT_SHARED,
        server_default=OrganizationPersonPassportStatusSummary.NOT_SHARED.value,
        index=True,
    )
    added_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        index=True,
    )
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    resolution_state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="unresolved",
        server_default="unresolved",
    )
    resolution_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolution_confidence: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    resolution_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    organization: Mapped["Organization"] = orm_relationship("Organization", back_populates="people")
    linked_user: Mapped["User | None"] = orm_relationship("User", foreign_keys=[linked_user_id])
    added_by_user: Mapped["User | None"] = orm_relationship("User", foreign_keys=[added_by_user_id])
    identifiers: Mapped[list["OrganizationPersonIdentifier"]] = orm_relationship(
        "OrganizationPersonIdentifier",
        back_populates="organization_person",
        cascade="all, delete-orphan",
    )
    notes: Mapped[list["OrganizationPersonNote"]] = orm_relationship(
        "OrganizationPersonNote",
        back_populates="organization_person",
        cascade="all, delete-orphan",
        order_by="OrganizationPersonNote.created_at.desc()",
    )
    passport_access_entries: Mapped[list["OrganizationPersonPassportAccess"]] = orm_relationship(
        "OrganizationPersonPassportAccess",
        back_populates="organization_person",
        cascade="all, delete-orphan",
        order_by="OrganizationPersonPassportAccess.granted_at.desc()",
    )
    trust_invitations: Mapped[list["TrustInvitation"]] = orm_relationship(
        "TrustInvitation",
        back_populates="organization_person",
    )
    verification_requests: Mapped[list["VerificationRequest"]] = orm_relationship(
        "VerificationRequest",
        back_populates="organization_person",
    )
    employments: Mapped[list["Employment"]] = orm_relationship(
        "Employment",
        back_populates="organization_person",
    )

    def __repr__(self) -> str:
        return (
            "OrganizationPerson("
            f"id={self.id}, public_id={self.public_id}, organization_id={self.organization_id}, "
            f"full_name={self.full_name!r})"
        )
