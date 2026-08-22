"""Persistent operational incident model for Admin System Operations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.system_incident_event import SystemIncidentEvent
    from app.models.user import User


class SystemIncident(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Small persisted operational incident for platform issues."""

    __tablename__ = "system_incidents"

    public_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        default=uuid.uuid4,
        unique=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="open",
        server_default="open",
        index=True,
    )
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="manual",
        server_default="manual",
    )
    reference_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_public_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_by_user: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_user_id])
    resolved_by_user: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[resolved_by_user_id],
    )
    events: Mapped[list["SystemIncidentEvent"]] = relationship(
        "SystemIncidentEvent",
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="SystemIncidentEvent.created_at.asc()",
    )
