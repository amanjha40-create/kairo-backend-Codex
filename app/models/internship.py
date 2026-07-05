"""Internship records — company placements with optional stipend details."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Internship(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """An internship at a company."""

    __tablename__ = "internships"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    company_name: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_ongoing: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    stipend_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    stipend_currency: Mapped[str] = mapped_column(String(8), default="INR", nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(48), nullable=False, default="pending", server_default="pending",
    )
    verifier_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"Internship(id={self.id}, company={self.company_name!r})"
