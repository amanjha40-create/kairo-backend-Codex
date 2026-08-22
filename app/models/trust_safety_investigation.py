"""Canonical Trust & Safety investigation workspace."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.risk_signal import RiskSignal
    from app.models.trust_safety_investigation_event import TrustSafetyInvestigationEvent
    from app.models.trust_safety_investigation_note import TrustSafetyInvestigationNote
    from app.models.user import User


class TrustSafetyInvestigation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Admin-only investigation for explainable risk review."""

    __tablename__ = "trust_safety_investigations"

    public_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        default=uuid.uuid4,
        unique=True,
        index=True,
    )
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    subject_public_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="open",
        server_default="open",
        index=True,
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    assigned_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
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
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    dismissal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_signal_detected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    assigned_admin_user: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[assigned_admin_user_id],
    )
    created_by_user: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[created_by_user_id],
    )
    resolved_by_user: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[resolved_by_user_id],
    )
    dismissed_by_user: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[dismissed_by_user_id],
    )
    signals: Mapped[list["RiskSignal"]] = relationship(
        "RiskSignal",
        back_populates="investigation",
        order_by="RiskSignal.detected_at.asc()",
    )
    notes: Mapped[list["TrustSafetyInvestigationNote"]] = relationship(
        "TrustSafetyInvestigationNote",
        back_populates="investigation",
        cascade="all, delete-orphan",
        order_by="TrustSafetyInvestigationNote.created_at.asc()",
    )
    events: Mapped[list["TrustSafetyInvestigationEvent"]] = relationship(
        "TrustSafetyInvestigationEvent",
        back_populates="investigation",
        cascade="all, delete-orphan",
        order_by="TrustSafetyInvestigationEvent.created_at.asc()",
    )
