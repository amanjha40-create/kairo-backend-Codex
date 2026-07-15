from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ResumeProcessingJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "resume_processing_jobs"
    __table_args__ = (UniqueConstraint("resume_document_id", "idempotency_key"),)

    resume_document_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("resume_documents.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    extraction_provider: Mapped[str] = mapped_column(String(64), nullable=False, default="textract")
    parsing_provider: Mapped[str] = mapped_column(String(64), nullable=False, default="bedrock")
    extraction_job_id: Mapped[str | None] = mapped_column(String(255))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_category: Mapped[str | None] = mapped_column(String(64))
    sanitized_failure_code: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parser_schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
