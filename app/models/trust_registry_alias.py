"""Alias model for Trust Registry records."""

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


class TrustRegistryAlias(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Alternate or historic names associated with a registry record."""

    __tablename__ = "trust_registry_aliases"
    __table_args__ = (
        UniqueConstraint(
            "registry_record_id",
            "alias_name",
            name="uq_trust_registry_aliases_registry_record_id_alias_name",
        ),
    )

    public_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True)
    registry_record_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("trust_registry_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alias_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    alias_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(
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

    registry_record: Mapped["TrustRegistryRecord"] = relationship("TrustRegistryRecord", back_populates="aliases")

