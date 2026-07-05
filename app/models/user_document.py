"""User identity documents — Aadhaar, PAN, License, etc. (NOT employment-tied)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class UserDocument(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Personal identity documents owned by a user — shared across employments."""

    __tablename__ = "user_documents"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    document_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    document_number: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    # S3 storage
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Verification workflow
    verification_status: Mapped[str] = mapped_column(
        String(48),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # License / passport expiry — for proactive renewal reminders
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    # AI-extracted fields (name, DOB, etc.) — optional, populated by extraction worker
    extracted_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    def __repr__(self) -> str:
        return f"UserDocument(id={self.id}, type={self.document_type!r})"
