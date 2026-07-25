"""Candidate-managed language entries."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class ProfileLanguage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "profile_languages"
    __table_args__ = (UniqueConstraint("user_id", "language", name="uq_profile_languages_user_language"),)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(80), nullable=False)
    proficiency: Mapped[str | None] = mapped_column(String(32), nullable=True)
    user: Mapped["User"] = relationship("User")
