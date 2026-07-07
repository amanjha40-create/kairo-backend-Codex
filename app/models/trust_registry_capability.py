"""Trust Registry capability catalog model."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.trust_registry_record_capability import TrustRegistryRecordCapability


class TrustRegistryCapability(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Catalog of generic trust capabilities supported by registry records."""

    __tablename__ = "trust_registry_capabilities"

    public_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True)
    capability_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    registry_records: Mapped[list["TrustRegistryRecordCapability"]] = relationship(
        "TrustRegistryRecordCapability",
        back_populates="capability",
    )

