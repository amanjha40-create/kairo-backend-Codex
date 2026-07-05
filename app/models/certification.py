"""Certifications — courses, professional certificates, and training records."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Certification(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A certification or course completion record owned by a user."""

    __tablename__ = "certifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    issuing_organization: Mapped[str] = mapped_column(String(512), nullable=False)
    issued_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    does_not_expire: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    credential_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    credential_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Optional uploaded certificate document (presigned S3)
    object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True, unique=True)
    original_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    verification_status: Mapped[str] = mapped_column(
        String(48),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"Certification(id={self.id}, title={self.title!r})"
