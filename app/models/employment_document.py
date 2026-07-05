"""Binary evidence attached to an employment case — S3 object metadata plus extraction state."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.pg_enums import document_extraction_status_enum, employment_document_type_enum
from app.employment.enums import (
    DocumentExtractionStatus,
    DocumentVerificationStatus,
    EmploymentDocumentType,
)

if TYPE_CHECKING:
    from app.models.employment import Employment


class EmploymentDocument(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Stored-file metadata; object bytes live in S3 under `object_key`."""

    __tablename__ = "employment_documents"

    employment_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employments.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    document_type: Mapped[str] = mapped_column(employment_document_type_enum, nullable=False, index=True)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    verification_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=DocumentVerificationStatus.PENDING_UPLOAD.value,
        index=True,
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    extraction_status: Mapped[str] = mapped_column(
        document_extraction_status_enum,
        nullable=False,
        default=DocumentExtractionStatus.PENDING.value,
        index=True,
    )
    extraction_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    extraction_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extraction_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extracted_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    employment: Mapped["Employment"] = relationship("Employment", back_populates="documents")

    def __repr__(self) -> str:
        return f"EmploymentDocument(id={self.id}, type={self.document_type!r})"

