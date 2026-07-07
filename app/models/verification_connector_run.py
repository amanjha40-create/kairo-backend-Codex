"""Verification connector execution-run model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.trust_registry_record import TrustRegistryRecord
    from app.models.verification_connector import VerificationConnector
    from app.models.verification_request import VerificationRequest


class VerificationConnectorRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable-ish execution record for a single connector attempt."""

    __tablename__ = "verification_connector_runs"

    public_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True)
    connector_key: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("verification_connectors.connector_key", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    verification_request_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("verification_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    registry_record_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("trust_registry_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    normalized_result: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    error: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    connector: Mapped["VerificationConnector"] = relationship(
        "VerificationConnector",
        back_populates="runs",
        primaryjoin="foreign(VerificationConnectorRun.connector_key) == VerificationConnector.connector_key",
    )
    verification_request: Mapped["VerificationRequest"] = relationship(
        "VerificationRequest",
        back_populates="connector_runs",
    )
    registry_record: Mapped["TrustRegistryRecord | None"] = relationship(
        "TrustRegistryRecord",
        back_populates="connector_runs",
    )

    def __repr__(self) -> str:
        return (
            "VerificationConnectorRun("
            f"id={self.id}, connector_key={self.connector_key!r}, status={self.status!r})"
        )
