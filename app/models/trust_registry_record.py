"""Canonical Trust Registry record model."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.trust_registry_alias import TrustRegistryAlias
    from app.models.trust_registry_domain import TrustRegistryDomain
    from app.models.trust_registry_identifier import TrustRegistryIdentifier
    from app.models.trust_registry_merge_history import TrustRegistryMergeHistory
    from app.models.trust_registry_record_capability import TrustRegistryRecordCapability
    from app.models.trust_registry_relationship import TrustRegistryRelationship
    from app.models.verification_request import VerificationRequest


class TrustRegistryRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Foundational registry entity for real-world trust authorities."""

    __tablename__ = "trust_registry_records"

    public_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True)
    registry_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    organization_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    state_province: Mapped[str | None] = mapped_column(String(128), nullable=True)
    website: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", server_default="draft", index=True)
    trust_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="unreviewed",
        server_default="unreviewed",
        index=True,
    )
    registry_confidence_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    trust_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    organizations: Mapped[list["Organization"]] = relationship("Organization", back_populates="registry_record")
    verification_requests: Mapped[list["VerificationRequest"]] = relationship(
        "VerificationRequest",
        back_populates="registry_record",
    )
    capabilities: Mapped[list["TrustRegistryRecordCapability"]] = relationship(
        "TrustRegistryRecordCapability",
        back_populates="registry_record",
        cascade="all, delete-orphan",
    )
    identifiers: Mapped[list["TrustRegistryIdentifier"]] = relationship(
        "TrustRegistryIdentifier",
        back_populates="registry_record",
        cascade="all, delete-orphan",
    )
    domains: Mapped[list["TrustRegistryDomain"]] = relationship(
        "TrustRegistryDomain",
        back_populates="registry_record",
        cascade="all, delete-orphan",
    )
    aliases: Mapped[list["TrustRegistryAlias"]] = relationship(
        "TrustRegistryAlias",
        back_populates="registry_record",
        cascade="all, delete-orphan",
    )
    parent_relationships: Mapped[list["TrustRegistryRelationship"]] = relationship(
        "TrustRegistryRelationship",
        back_populates="parent_registry_record",
        foreign_keys="TrustRegistryRelationship.parent_registry_record_id",
        cascade="all, delete-orphan",
    )
    child_relationships: Mapped[list["TrustRegistryRelationship"]] = relationship(
        "TrustRegistryRelationship",
        back_populates="child_registry_record",
        foreign_keys="TrustRegistryRelationship.child_registry_record_id",
        cascade="all, delete-orphan",
    )
    source_merge_history: Mapped[list["TrustRegistryMergeHistory"]] = relationship(
        "TrustRegistryMergeHistory",
        back_populates="source_registry_record",
        foreign_keys="TrustRegistryMergeHistory.source_registry_record_id",
    )
    target_merge_history: Mapped[list["TrustRegistryMergeHistory"]] = relationship(
        "TrustRegistryMergeHistory",
        back_populates="target_registry_record",
        foreign_keys="TrustRegistryMergeHistory.target_registry_record_id",
    )

    def __repr__(self) -> str:
        return f"TrustRegistryRecord(id={self.id}, registry_code={self.registry_code!r}, legal_name={self.legal_name!r})"
