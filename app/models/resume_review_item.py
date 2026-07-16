from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ResumeReviewItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "resume_review_items"
    __table_args__ = (UniqueConstraint("review_session_id", "source_claim_id"),)

    review_session_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("resume_review_sessions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    claim_type: Mapped[str] = mapped_column(String(32), index=True)
    source_claim_id: Mapped[str] = mapped_column(String(64))
    original_payload: Mapped[dict] = mapped_column(JSONB)
    edited_payload: Mapped[dict] = mapped_column(JSONB)
    selected: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    review_status: Mapped[str] = mapped_column(String(32), default="pending", server_default="pending")
    duplicate_status: Mapped[str] = mapped_column(String(32), default="no_match", server_default="no_match")
    duplicate_candidates: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    conflict_warnings: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    import_action: Mapped[str] = mapped_column(String(32), default="skip", server_default="skip")
    target_record_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    imported_record_type: Mapped[str | None] = mapped_column(String(32))
    imported_record_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    source_reference: Mapped[str | None] = mapped_column(String(512))
    confidence: Mapped[float | None] = mapped_column(Float)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

