"""Public Trust Passport view events."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin


class PassportShareView(UUIDPrimaryKeyMixin, Base):
    """A single successful public passport page load."""

    __tablename__ = "passport_share_views"

    share_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("passport_share_links.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    viewer_ip_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    referrer: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    is_unique_view: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return f"PassportShareView(share_id={self.share_id}, unique={self.is_unique_view})"
