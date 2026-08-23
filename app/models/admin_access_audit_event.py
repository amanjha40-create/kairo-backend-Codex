"""Append-only audit trail for Admin access and settings changes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class AdminAccessAuditEvent(UUIDPrimaryKeyMixin, Base):
    """Immutable event log for sensitive internal Admin-access actions."""

    __tablename__ = "admin_access_audit_events"

    public_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        default=uuid.uuid4,
        unique=True,
        index=True,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    subject_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    invitation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("admin_access_invitations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_role: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    actor_display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject_email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_payload: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    actor_user: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[actor_user_id],
        back_populates="admin_access_audit_events_as_actor",
    )
    subject_user: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[subject_user_id],
        back_populates="admin_access_audit_events_as_subject",
    )
