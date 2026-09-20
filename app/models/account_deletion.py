"""Durable erasure intent; deliberately independent of deletable source rows."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AccountDeletion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "account_deletions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('purge_pending','purge_partial','operator_review','complete')",
            name="status",
        ),
        CheckConstraint("retry_count >= 0", name="retry_count"),
        Index("ix_account_deletions_scan", "next_attempt_at", "status"),
    )
    # Minimal non-content tombstone, not a cascading FK: erasure work survives user removal.
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    storage_bucket: Mapped[str | None] = mapped_column(String(255))
    storage_prefix: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(32), default="purge_pending")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    db_committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    purge_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error_category: Mapped[str | None] = mapped_column(String(64))
    items: Mapped[list[AccountDeletionItem]] = relationship(back_populates="request", lazy="raise")


class AccountDeletionItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "account_deletion_items"
    __table_args__ = (
        UniqueConstraint("deletion_id", "identity_hash", name="uq_account_deletion_item_identity"),
        CheckConstraint("kind IN ('object','namespace','otp','unresolved')", name="kind"),
        CheckConstraint("status IN ('pending','retry','complete','review')", name="status"),
        CheckConstraint("attempts >= 0", name="attempts"),
        Index("ix_account_deletion_items_scan", "deletion_id", "status", "next_attempt_at"),
    )
    deletion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("account_deletions.id", ondelete="RESTRICT")
    )
    identity_hash: Mapped[str] = mapped_column(String(64))
    source_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(16))
    object_key: Mapped[str | None] = mapped_column(String(1024))
    # Exact allowed namespace is captured from canonical ownership, never supplied by a client.
    scope_prefix: Mapped[str | None] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_error_category: Mapped[str | None] = mapped_column(String(64))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request: Mapped[AccountDeletion] = relationship(back_populates="items")
