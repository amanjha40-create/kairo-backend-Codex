"""Verification connector catalog model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.verification_connector_run import VerificationConnectorRun


class VerificationConnector(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Catalog entry describing an available verification connector implementation."""

    __tablename__ = "verification_connectors"

    public_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True)
    connector_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    connector_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    supported_capabilities: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    supported_registry_types: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    health_status: Mapped[str] = mapped_column(String(32), nullable=False, default="healthy", server_default="healthy")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100")
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    last_health_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    runs: Mapped[list["VerificationConnectorRun"]] = relationship(
        "VerificationConnectorRun",
        back_populates="connector",
        cascade="all, delete-orphan",
        primaryjoin="VerificationConnector.connector_key == foreign(VerificationConnectorRun.connector_key)",
        order_by="VerificationConnectorRun.started_at.desc()",
    )

    def __repr__(self) -> str:
        return f"VerificationConnector(id={self.id}, connector_key={self.connector_key!r}, enabled={self.enabled})"
