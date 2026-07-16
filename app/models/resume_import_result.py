from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ResumeImportResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "resume_import_results"
    __table_args__ = (UniqueConstraint("import_batch_id", "review_item_id"),)

    import_batch_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("resume_import_batches.id", ondelete="CASCADE"), index=True)
    review_item_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("resume_review_items.id", ondelete="CASCADE"), index=True)
    outcome: Mapped[str] = mapped_column(String(32))
    record_type: Mapped[str | None] = mapped_column(String(32))
    record_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    sanitized_error_code: Mapped[str | None] = mapped_column(String(64))
    warnings: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")

