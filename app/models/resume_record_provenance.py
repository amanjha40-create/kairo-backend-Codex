from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ResumeRecordProvenance(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "resume_record_provenance"
    __table_args__ = (UniqueConstraint("review_item_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    record_type: Mapped[str] = mapped_column(String(32), index=True)
    record_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    resume_document_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("resume_documents.id", ondelete="CASCADE"))
    parsed_result_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("resume_parsed_results.id", ondelete="CASCADE"))
    review_session_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("resume_review_sessions.id", ondelete="CASCADE"))
    review_item_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("resume_review_items.id", ondelete="CASCADE"), unique=True)
    import_batch_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("resume_import_batches.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(32), default="resume", server_default="resume")
    original_payload_hash: Mapped[str] = mapped_column(String(64))
    edited_payload_hash: Mapped[str] = mapped_column(String(64))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
