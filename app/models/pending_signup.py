"""Staged signup before email OTP verification."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class PendingSignup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Holds credential intent until OTP is verified and a User row is created."""

    __tablename__ = "pending_signups"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    otp_sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verify_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_otp_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
