from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ResumeParsedResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "resume_parsed_results"

    job_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("resume_processing_jobs.id", ondelete="CASCADE"), unique=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    structured_result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    parser_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    warnings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
