"""Admin-only internal notes attached to candidate accounts."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class UserAdminNote(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only internal notes for candidate account operations."""

    __tablename__ = "user_admin_notes"

    public_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        default=uuid.uuid4,
        unique=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    author_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    author_display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    user: Mapped["User"] = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="admin_notes",
    )
    author_user: Mapped["User | None"] = relationship("User", foreign_keys=[author_user_id])
