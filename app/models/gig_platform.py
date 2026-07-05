"""Gig worker platform partnerships — Swiggy, Uber, Zomato, Porter, etc."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class GigPlatform(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A gig worker's active or past partnership with a platform."""

    __tablename__ = "gig_platforms"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    platform_name: Mapped[str] = mapped_column(String(256), nullable=False)
    partner_role: Mapped[str] = mapped_column(String(256), nullable=False)
    started_at: Mapped[date] = mapped_column(Date, nullable=False)
    ended_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    partner_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(48), nullable=False, default="pending", server_default="pending",
    )

    def __repr__(self) -> str:
        return f"GigPlatform(id={self.id}, platform={self.platform_name!r})"
