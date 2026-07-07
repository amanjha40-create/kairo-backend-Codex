"""Auditable merge history for Trust Registry records."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.trust_registry_record import TrustRegistryRecord


class TrustRegistryMergeHistory(UUIDPrimaryKeyMixin, Base):
    """Immutable merge audit trail for consolidated registry records."""

    __tablename__ = "trust_registry_merge_history"

    public_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True)
    source_registry_record_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("trust_registry_records.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    target_registry_record_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("trust_registry_records.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    merged_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    merge_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    source_registry_record: Mapped["TrustRegistryRecord"] = relationship(
        "TrustRegistryRecord",
        back_populates="source_merge_history",
        foreign_keys=[source_registry_record_id],
    )
    target_registry_record: Mapped["TrustRegistryRecord"] = relationship(
        "TrustRegistryRecord",
        back_populates="target_merge_history",
        foreign_keys=[target_registry_record_id],
    )
