"""Linked OAuth accounts — one row per (user, provider) pair."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class UserSocialAccount(UUIDPrimaryKeyMixin, Base):
    """Stores one row per linked OAuth provider per user."""

    __tablename__ = "user_social_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_social_provider_user"),
        UniqueConstraint("user_id", "provider", name="uq_social_user_provider"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)          # "google" | "linkedin" | "github"
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False) # sub / id from provider
    provider_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship("User", back_populates="social_accounts")

    def __repr__(self) -> str:
        return f"UserSocialAccount(user_id={self.user_id}, provider={self.provider!r})"
