"""Immutable verification audit stream — compliance and forensic replay."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin
from app.db.pg_enums import verification_audit_action_enum

if TYPE_CHECKING:
    from app.models.employment import Employment


class VerificationAuditEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only events; soft-delete is intentionally omitted."""

    __tablename__ = "verification_audit_events"

    employment_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employments.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Snapshot of actor role at time of action — immutable history
    # ("user" | "hr" | "admin" | "superadmin" | null for system events)
    actor_role: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # Snapshot of actor's display name (full_name or email) — survives user deletion
    actor_display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(verification_audit_action_enum, nullable=False, index=True)
    previous_status: Mapped[str | None] = mapped_column(String(48), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(48), nullable=True)
    metadata_payload: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    employment: Mapped["Employment"] = relationship("Employment", back_populates="audit_events")

    def __repr__(self) -> str:
        return f"VerificationAuditEvent(id={self.id}, action={self.action!r})"

