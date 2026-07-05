"""Profile view events — one row per unique IP+profile per 24-hour window."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin


class ProfileView(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "profile_views"

    profile_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # SHA-256 of the viewer's IP — never store raw IPs.
    viewer_ip_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Set when the viewer is a logged-in Kairo user.
    viewer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return f"ProfileView(profile={self.profile_user_id}, ip_hash={self.viewer_ip_hash[:8]}…)"
