"""Lifecycle events for trust invitations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.trust_invitation import TrustInvitation
    from app.models.user import User


class TrustInvitationEvent(UUIDPrimaryKeyMixin, Base):
    """Immutable invitation lifecycle event."""

    __tablename__ = "trust_invitation_events"

    invitation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("trust_invitations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    metadata_payload: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        index=True,
    )

    invitation: Mapped["TrustInvitation"] = relationship("TrustInvitation", back_populates="events")
    actor_user: Mapped["User | None"] = relationship("User")

    def __repr__(self) -> str:
        return f"TrustInvitationEvent(id={self.id}, invitation_id={self.invitation_id}, event_type={self.event_type!r})"
