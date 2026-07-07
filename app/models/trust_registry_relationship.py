"""Hierarchy and relationship model for Trust Registry records."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.trust_registry_record import TrustRegistryRecord


class TrustRegistryRelationship(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Parent-child or affiliated relationships between registry records."""

    __tablename__ = "trust_registry_relationships"
    __table_args__ = (
        UniqueConstraint(
            "parent_registry_record_id",
            "child_registry_record_id",
            "relationship_type",
            name="uq_trust_registry_relationships_parent_child_type",
        ),
    )

    public_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True)
    parent_registry_record_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("trust_registry_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    child_registry_record_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("trust_registry_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relationship_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", server_default="active")
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    parent_registry_record: Mapped["TrustRegistryRecord"] = relationship(
        "TrustRegistryRecord",
        back_populates="parent_relationships",
        foreign_keys=[parent_registry_record_id],
    )
    child_registry_record: Mapped["TrustRegistryRecord"] = relationship(
        "TrustRegistryRecord",
        back_populates="child_relationships",
        foreign_keys=[child_registry_record_id],
    )

