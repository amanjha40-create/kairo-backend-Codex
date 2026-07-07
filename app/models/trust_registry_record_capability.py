"""Capability assignments for Trust Registry records."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.trust_registry_capability import TrustRegistryCapability
    from app.models.trust_registry_record import TrustRegistryRecord


class TrustRegistryRecordCapability(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Normalized capability mapping with provenance."""

    __tablename__ = "trust_registry_record_capabilities"
    __table_args__ = (
        UniqueConstraint(
            "registry_record_id",
            "capability_id",
            name="uq_trust_registry_record_capabilities_registry_record_id_capability_id",
        ),
    )

    public_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True)
    registry_record_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("trust_registry_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    capability_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("trust_registry_capabilities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", server_default="active")
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    registry_record: Mapped["TrustRegistryRecord"] = relationship("TrustRegistryRecord", back_populates="capabilities")
    capability: Mapped["TrustRegistryCapability"] = relationship("TrustRegistryCapability", back_populates="registry_records")

