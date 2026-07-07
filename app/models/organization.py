"""Organization model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.pg_enums import organization_type_enum
from app.organization.enums import OrganizationType

if TYPE_CHECKING:
    from app.models.organization_member import OrganizationMember
    from app.models.trust_registry_record import TrustRegistryRecord
    from app.models.trust_invitation import TrustInvitation
    from app.models.verification_request import VerificationRequest


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tenant-aware organization owned and managed by Kairo users."""

    __tablename__ = "organizations"

    public_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    organization_type: Mapped[OrganizationType] = mapped_column(organization_type_enum, nullable=False)
    verification_capabilities: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    registry_record_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("trust_registry_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    registry_resolution_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    registry_resolution_confidence: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    registry_resolution_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    registry_resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    registry_resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    members: Mapped[list["OrganizationMember"]] = relationship(
        "OrganizationMember",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    trust_invitations: Mapped[list["TrustInvitation"]] = relationship(
        "TrustInvitation",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    verification_requests: Mapped[list["VerificationRequest"]] = relationship(
        "VerificationRequest",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    registry_record: Mapped["TrustRegistryRecord | None"] = relationship("TrustRegistryRecord", back_populates="organizations")

    def __repr__(self) -> str:
        return f"Organization(id={self.id}, public_id={self.public_id}, name={self.name!r})"
