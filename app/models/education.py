"""Education records — degrees, diplomas, certifications."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.education_document import EducationDocument


class Education(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A single education credential (degree / diploma / certification)."""

    __tablename__ = "educations"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    institution_name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    degree: Mapped[str] = mapped_column(String(255), nullable=False)
    field_of_study: Mapped[str | None] = mapped_column(String(255), nullable=True)
    education_level: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    grade: Mapped[str | None] = mapped_column(String(64), nullable=True)

    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_currently_studying: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )

    # Verification workflow
    verification_status: Mapped[str] = mapped_column(
        String(48), nullable=False, default="draft", server_default="draft",
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    documents: Mapped[list["EducationDocument"]] = relationship(
        "EducationDocument",
        back_populates="education",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"Education(id={self.id}, institution={self.institution_name!r})"
