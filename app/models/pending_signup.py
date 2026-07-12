"""Staged signup before dual-channel verification and final account creation."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class PendingSignup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Holds credential intent until both channels are verified and a User row is created."""

    __tablename__ = "pending_signups"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True, index=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    email_otp_sent_count: Mapped[int] = mapped_column("otp_sent_count", Integer, nullable=False, default=0)
    email_verify_attempt_count: Mapped[int] = mapped_column(
        "verify_attempt_count",
        Integer,
        nullable=False,
        default=0,
    )
    email_last_otp_sent_at: Mapped[datetime | None] = mapped_column(
        "last_otp_sent_at",
        DateTime(timezone=True),
        nullable=True,
    )
    phone_otp_sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    phone_verify_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    phone_last_otp_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
